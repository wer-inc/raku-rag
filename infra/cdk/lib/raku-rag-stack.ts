import * as cdk from "aws-cdk-lib";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import * as cognito from "aws-cdk-lib/aws-cognito";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as ecsPatterns from "aws-cdk-lib/aws-ecs-patterns";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as kms from "aws-cdk-lib/aws-kms";
import * as logs from "aws-cdk-lib/aws-logs";
import * as rds from "aws-cdk-lib/aws-rds";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as sqs from "aws-cdk-lib/aws-sqs";
import * as wafv2 from "aws-cdk-lib/aws-wafv2";
import * as path from "path";
import { Construct } from "constructs";

// Docker build context = repo root (the Dockerfiles use npm workspaces / src+workers).
const REPO_ROOT = path.join(__dirname, "..", "..", "..");
// Build POSTGRES_URL at container start from the injected DATABASE_* parts (the password is a secret
// env, so it must be assembled at runtime, not baked into a plain env var). DB user = the Aurora
// master "raku_rag"; the app then SET ROLE raku_app for RLS.
const PG_URL_EXPR =
  "postgresql://raku_rag:${DATABASE_PASSWORD}@${DATABASE_HOST}:${DATABASE_PORT}/${DATABASE_NAME}";

export type FrontendHostingMode = "external-vercel" | "aws-nextjs";

export interface RakuRagStackProps extends cdk.StackProps {
  readonly stageName: string;
  readonly frontendHosting?: FrontendHostingMode;
}

export class RakuRagStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: RakuRagStackProps) {
    super(scope, id, props);

    const servicePrefix = `raku-rag-${props.stageName}`;
    const isProd = props.stageName === "prod";
    const removalPolicy = isProd ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY;
    const pgvectorExtensionSql = "CREATE EXTENSION IF NOT EXISTS vector;";

    // minimalSpec — size the stack for "lowest cost that still works" (single Aurora instance, small
    // Fargate tasks, Langfuse observability off). This is DECOUPLED from durability: isProd still
    // governs RETAIN / backups / deletion-protection. Default: on for any non-prod stage, off for prod;
    // override either way with `--context minimalSpec=true|false`
    // (e.g. `stage=prod --context minimalSpec=true` = a durable production env at minimal cost).
    const minimalSpecCtx = this.node.tryGetContext("minimalSpec");
    const minimalSpec =
      minimalSpecCtx === "true" || (minimalSpecCtx !== "false" && !isProd);
    const deployLangfuse = !minimalSpec;
    const fargateSize = {
      api: minimalSpec ? { cpu: 512, memoryLimitMiB: 1024 } : { cpu: 1024, memoryLimitMiB: 2048 },
      worker: minimalSpec ? { cpu: 256, memoryLimitMiB: 512 } : { cpu: 512, memoryLimitMiB: 1024 },
      answer: minimalSpec ? { cpu: 512, memoryLimitMiB: 1024 } : { cpu: 1024, memoryLimitMiB: 2048 }
    };

    cdk.Tags.of(this).add("app", "raku-rag");
    cdk.Tags.of(this).add("stage", props.stageName);

    const vpc = new ec2.Vpc(this, "Vpc", {
      maxAzs: 2,
      natGateways: 1,
      subnetConfiguration: [
        {
          name: "public",
          subnetType: ec2.SubnetType.PUBLIC,
          cidrMask: 24
        },
        {
          name: "private-egress",
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
          cidrMask: 24
        },
        {
          name: "private-isolated",
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
          cidrMask: 24
        }
      ]
    });

    const dataKey = new kms.Key(this, "DataKey", {
      alias: `${servicePrefix}-data-key`,
      description: "Customer data encryption key for raku-rag storage, queues, and database",
      enableKeyRotation: true,
      removalPolicy
    });

    const documentBucket = new s3.Bucket(this, "DocumentBucket", {
      bucketName: `${servicePrefix}-${cdk.Aws.ACCOUNT_ID}-${cdk.Aws.REGION}-documents`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: dataKey,
      enforceSSL: true,
      versioned: true,
      removalPolicy
    });

    const deadLetterQueue = new sqs.Queue(this, "IngestionDeadLetterQueue", {
      queueName: `${servicePrefix}-ingestion-dlq`,
      encryption: sqs.QueueEncryption.KMS,
      encryptionMasterKey: dataKey,
      retentionPeriod: cdk.Duration.days(14)
    });

    const ingestionQueue = new sqs.Queue(this, "IngestionQueue", {
      queueName: `${servicePrefix}-ingestion`,
      encryption: sqs.QueueEncryption.KMS,
      encryptionMasterKey: dataKey,
      visibilityTimeout: cdk.Duration.minutes(5),
      retentionPeriod: cdk.Duration.days(4),
      deadLetterQueue: {
        queue: deadLetterQueue,
        maxReceiveCount: 5
      }
    });

    const appSecret = new secretsmanager.Secret(this, "ApplicationSecret", {
      secretName: `${servicePrefix}/application`,
      description: "NestJS API signing and provider integration secret material",
      encryptionKey: dataKey,
      generateSecretString: {
        secretStringTemplate: JSON.stringify({
          jwtIssuer: servicePrefix
        }),
        generateStringKey: "jwtSigningSecret",
        excludePunctuation: true
      }
    });

    // Shared internal-boundary secret: the API forwards it as X-Internal-Auth and the answer-service
    // enforces it on every /internal/* call (apps/answer-service + auth/internal-auth.ts).
    const internalAuthSecret = new secretsmanager.Secret(this, "InternalAuthSecret", {
      secretName: `${servicePrefix}/internal-auth`,
      description: "Shared secret for the API -> answer-service internal boundary",
      encryptionKey: dataKey,
      generateSecretString: {
        secretStringTemplate: JSON.stringify({ purpose: "internal-auth" }),
        generateStringKey: "secret",
        excludePunctuation: true
      }
    });

    const langfuseSecret = new secretsmanager.Secret(this, "LangfuseSecret", {
      secretName: `${servicePrefix}/langfuse`,
      description: "Langfuse auth and encryption secret material",
      encryptionKey: dataKey,
      generateSecretString: {
        secretStringTemplate: JSON.stringify({
          telemetryEnabled: false
        }),
        generateStringKey: "nextauthSecret",
        excludePunctuation: true
      }
    });

    const userPool = new cognito.UserPool(this, "UserPool", {
      userPoolName: `${servicePrefix}-users`,
      selfSignUpEnabled: false,
      signInAliases: { email: true },
      mfa: cognito.Mfa.OPTIONAL,
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      removalPolicy
    });

    const userPoolClient = userPool.addClient("UserPoolClient", {
      userPoolClientName: `${servicePrefix}-web`,
      generateSecret: false,
      authFlows: {
        userPassword: true,
        userSrp: true
      },
      oAuth: {
        flows: {
          authorizationCodeGrant: true
        },
        scopes: [cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE],
        callbackUrls: ["http://localhost:3000/api/auth/callback/cognito"],
        logoutUrls: ["http://localhost:3000"]
      }
    });

    const ecsSecurityGroup = new ec2.SecurityGroup(this, "EcsSecurityGroup", {
      vpc,
      allowAllOutbound: true,
      description: "Fargate tasks for API, worker, Langfuse, and optional web fallback"
    });

    const databaseSecurityGroup = new ec2.SecurityGroup(this, "DatabaseSecurityGroup", {
      vpc,
      allowAllOutbound: false,
      description: "Aurora PostgreSQL Serverless v2 with pgvector"
    });
    databaseSecurityGroup.addIngressRule(
      ecsSecurityGroup,
      ec2.Port.tcp(5432),
      "Allow ECS tasks to reach Aurora PostgreSQL"
    );

    const database = new rds.DatabaseCluster(this, "AuroraPgvectorCluster", {
      clusterIdentifier: `${servicePrefix}-aurora-pgvector`,
      engine: rds.DatabaseClusterEngine.auroraPostgres({
        version: rds.AuroraPostgresEngineVersion.of("16.1", "16")
      }),
      credentials: rds.Credentials.fromGeneratedSecret("raku_rag", {
        encryptionKey: dataKey,
        secretName: `${servicePrefix}/aurora`
      }),
      defaultDatabaseName: "raku_rag",
      writer: rds.ClusterInstance.serverlessV2("writer", {
        publiclyAccessible: false
      }),
      // HA reader only when NOT minimal — a second always-on Serverless v2 instance is the single
      // biggest cost line, so the minimal tier runs a lone writer.
      readers: minimalSpec
        ? []
        : [
            rds.ClusterInstance.serverlessV2("reader", {
              scaleWithWriter: true,
              publiclyAccessible: false
            })
          ],
      serverlessV2MinCapacity: 0.5,
      serverlessV2MaxCapacity: minimalSpec ? 2 : 4,
      storageEncrypted: true,
      storageEncryptionKey: dataKey,
      backup: {
        retention: cdk.Duration.days(isProd ? 35 : 7)
      },
      deletionProtection: isProd,
      removalPolicy,
      vpc,
      vpcSubnets: {
        subnetType: ec2.SubnetType.PRIVATE_ISOLATED
      },
      securityGroups: [databaseSecurityGroup]
    });

    const cluster = new ecs.Cluster(this, "EcsCluster", {
      clusterName: `${servicePrefix}-cluster`,
      vpc,
      containerInsightsV2: ecs.ContainerInsights.ENABLED
    });

    const apiTask = new ecs.FargateTaskDefinition(this, "ApiTaskDefinition", {
      family: `${servicePrefix}-api`,
      cpu: fargateSize.api.cpu,
      memoryLimitMiB: fargateSize.api.memoryLimitMiB,
      runtimePlatform: {
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
        cpuArchitecture: ecs.CpuArchitecture.X86_64
      }
    });
    this.attachRuntimePolicies(apiTask.taskRole, documentBucket, dataKey);
    ingestionQueue.grantSendMessages(apiTask.taskRole);
    appSecret.grantRead(apiTask.taskRole);
    internalAuthSecret.grantRead(apiTask.taskRole);
    database.secret?.grantRead(apiTask.taskRole);

    const apiContainer = apiTask.addContainer("NestjsApiContainer", {
      image: ecs.ContainerImage.fromAsset(REPO_ROOT, { file: "apps/api/Dockerfile" }),
      essential: true,
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: "api",
        logRetention: logs.RetentionDays.ONE_MONTH
      }),
      environment: {
        NODE_ENV: "production",
        STAGE_NAME: props.stageName,
        DOCUMENT_BUCKET: documentBucket.bucketName,
        INGESTION_QUEUE_URL: ingestionQueue.queueUrl,
        COGNITO_USER_POOL_ID: userPool.userPoolId,
        COGNITO_USER_POOL_CLIENT_ID: userPoolClient.userPoolClientId,
        DATABASE_HOST: database.clusterEndpoint.hostname,
        DATABASE_PORT: database.clusterEndpoint.port.toString(),
        DATABASE_NAME: "raku_rag",
        PGVECTOR_EXTENSION_SQL: pgvectorExtensionSql
      },
      secrets: {
        APPLICATION_SECRET: ecs.Secret.fromSecretsManager(appSecret),
        RAKU_TOKEN_SIGNING_SECRET: ecs.Secret.fromSecretsManager(appSecret, "jwtSigningSecret"),
        RAKU_INTERNAL_AUTH_SECRET: ecs.Secret.fromSecretsManager(internalAuthSecret, "secret"),
        DATABASE_PASSWORD: ecs.Secret.fromSecretsManager(database.secret!, "password")
      }
    });
    apiContainer.addPortMappings({ containerPort: 3000 });

    const apiService = new ecsPatterns.ApplicationLoadBalancedFargateService(
      this,
      "NestjsApiService",
      {
        cluster,
        taskDefinition: apiTask,
        serviceName: `${servicePrefix}-api`,
        publicLoadBalancer: true,
        listenerPort: 80,
        desiredCount: isProd ? 2 : 1,
        minHealthyPercent: 100,
        circuitBreaker: { rollback: true },
        assignPublicIp: false,
        securityGroups: [ecsSecurityGroup],
        taskSubnets: {
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS
        },
        healthCheckGracePeriod: cdk.Duration.seconds(60)
      }
    );
    apiService.targetGroup.configureHealthCheck({
      path: "/healthz",
      healthyHttpCodes: "200-399"
    });

    const apiWebAcl = new wafv2.CfnWebACL(this, "ApiWebAcl", {
      name: `${servicePrefix}-api-web-acl`,
      scope: "REGIONAL",
      defaultAction: { allow: {} },
      description: "Edge protection for the public NestJS API ALB",
      visibilityConfig: this.wafVisibilityConfig(`${servicePrefix}-api-web-acl`),
      rules: [
        {
          name: "AWSManagedCommonRuleSet",
          priority: 0,
          overrideAction: { none: {} },
          statement: {
            managedRuleGroupStatement: {
              vendorName: "AWS",
              name: "AWSManagedRulesCommonRuleSet"
            }
          },
          visibilityConfig: this.wafVisibilityConfig(`${servicePrefix}-aws-common-rules`)
        },
        {
          name: "IpRateLimit",
          priority: 10,
          action: { block: {} },
          statement: {
            rateBasedStatement: {
              aggregateKeyType: "IP",
              limit: isProd ? 2000 : 1000
            }
          },
          visibilityConfig: this.wafVisibilityConfig(`${servicePrefix}-ip-rate-limit`)
        },
        {
          name: "UserTokenRateLimit",
          priority: 20,
          action: { block: {} },
          statement: {
            rateBasedStatement: {
              aggregateKeyType: "CUSTOM_KEYS",
              customKeys: [
                {
                  header: {
                    name: "x-user-token",
                    textTransformations: [{ priority: 0, type: "NONE" }]
                  }
                }
              ],
              limit: isProd ? 600 : 300,
              scopeDownStatement: {
                sizeConstraintStatement: {
                  comparisonOperator: "GT",
                  fieldToMatch: { singleHeader: { name: "x-user-token" } },
                  size: 0,
                  textTransformations: [{ priority: 0, type: "NONE" }]
                }
              }
            }
          },
          visibilityConfig: this.wafVisibilityConfig(`${servicePrefix}-user-token-rate-limit`)
        }
      ]
    });
    new wafv2.CfnWebACLAssociation(this, "ApiWebAclAssociation", {
      resourceArn: apiService.loadBalancer.loadBalancerArn,
      webAclArn: apiWebAcl.attrArn
    });

    const workerTask = new ecs.FargateTaskDefinition(this, "PythonWorkerTaskDefinition", {
      family: `${servicePrefix}-worker`,
      cpu: fargateSize.worker.cpu,
      memoryLimitMiB: fargateSize.worker.memoryLimitMiB,
      runtimePlatform: {
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
        cpuArchitecture: ecs.CpuArchitecture.X86_64
      }
    });
    this.attachRuntimePolicies(workerTask.taskRole, documentBucket, dataKey);
    ingestionQueue.grantConsumeMessages(workerTask.taskRole);
    deadLetterQueue.grantSendMessages(workerTask.taskRole);
    database.secret?.grantRead(workerTask.taskRole);

    this.grantBedrockInvoke(workerTask.taskRole);
    workerTask.addContainer("PythonIngestWorkerContainer", {
      image: ecs.ContainerImage.fromAsset(REPO_ROOT, { file: "workers/ingest/Dockerfile" }),
      entryPoint: ["/bin/sh", "-c"],
      command: [`POSTGRES_URL="${PG_URL_EXPR}" exec python -m workers.ingest.worker --serve`],
      essential: true,
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: "worker",
        logRetention: logs.RetentionDays.ONE_MONTH
      }),
      environment: {
        STAGE_NAME: props.stageName,
        RAKU_WORKER_BACKEND: "postgres",
        DOCUMENT_BUCKET: documentBucket.bucketName,
        SQS_QUEUE_URL: ingestionQueue.queueUrl,
        SQS_DLQ_URL: deadLetterQueue.queueUrl,
        SQS_MAX_RECEIVE_COUNT: "5",
        DATABASE_HOST: database.clusterEndpoint.hostname,
        DATABASE_PORT: database.clusterEndpoint.port.toString(),
        DATABASE_NAME: "raku_rag",
        PGVECTOR_EXTENSION_SQL: pgvectorExtensionSql
      },
      secrets: {
        DATABASE_PASSWORD: ecs.Secret.fromSecretsManager(database.secret!, "password")
      }
    });

    const workerService = new ecs.FargateService(this, "PythonWorkerService", {
      cluster,
      serviceName: `${servicePrefix}-worker`,
      taskDefinition: workerTask,
      desiredCount: isProd ? 2 : 1,
      minHealthyPercent: 100,
      assignPublicIp: false,
      vpcSubnets: {
        subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS
      },
      securityGroups: [ecsSecurityGroup],
      circuitBreaker: {
        rollback: true
      }
    });

    // Python answer-service — the internal HTTP boundary serving /internal/* (retrieval / ACL /
    // ranking / manufacturing safety overlay) over the Postgres-backed ProductionSystem. The NestJS
    // API proxies to it; it is internal-only (no public ALB).
    const answerTask = new ecs.FargateTaskDefinition(this, "AnswerServiceTaskDefinition", {
      family: `${servicePrefix}-answer`,
      cpu: fargateSize.answer.cpu,
      memoryLimitMiB: fargateSize.answer.memoryLimitMiB,
      runtimePlatform: {
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
        cpuArchitecture: ecs.CpuArchitecture.X86_64
      }
    });
    this.attachRuntimePolicies(answerTask.taskRole, documentBucket, dataKey);
    this.grantBedrockInvoke(answerTask.taskRole);
    internalAuthSecret.grantRead(answerTask.taskRole);
    database.secret?.grantRead(answerTask.taskRole);

    const answerContainer = answerTask.addContainer("AnswerServiceContainer", {
      image: ecs.ContainerImage.fromAsset(REPO_ROOT, { file: "apps/answer-service/Dockerfile" }),
      entryPoint: ["/bin/sh", "-c"],
      command: [`POSTGRES_URL="${PG_URL_EXPR}" exec python apps/answer-service/server.py --port 8088`],
      essential: true,
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: "answer",
        logRetention: logs.RetentionDays.ONE_MONTH
      }),
      environment: {
        STAGE_NAME: props.stageName,
        DATABASE_HOST: database.clusterEndpoint.hostname,
        DATABASE_PORT: database.clusterEndpoint.port.toString(),
        DATABASE_NAME: "raku_rag"
      },
      secrets: {
        RAKU_INTERNAL_AUTH_SECRET: ecs.Secret.fromSecretsManager(internalAuthSecret, "secret"),
        DATABASE_PASSWORD: ecs.Secret.fromSecretsManager(database.secret!, "password")
      }
    });
    answerContainer.addPortMappings({ containerPort: 8088 });

    const answerService = new ecsPatterns.ApplicationLoadBalancedFargateService(
      this,
      "AnswerService",
      {
        cluster,
        taskDefinition: answerTask,
        serviceName: `${servicePrefix}-answer`,
        publicLoadBalancer: false, // internal — reached by the API over the VPC only
        listenerPort: 8088,
        desiredCount: isProd ? 2 : 1,
        minHealthyPercent: 100,
        circuitBreaker: { rollback: true },
        assignPublicIp: false,
        securityGroups: [ecsSecurityGroup],
        taskSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
        healthCheckGracePeriod: cdk.Duration.seconds(90)
      }
    );
    answerService.targetGroup.configureHealthCheck({
      path: "/healthz",
      healthyHttpCodes: "200-399"
    });
    // Wire the API -> answer-service internal endpoint now that both exist.
    apiContainer.addEnvironment(
      "ANSWER_SERVICE_URL",
      `http://${answerService.loadBalancer.loadBalancerDnsName}:8088`
    );

    // Langfuse (self-hosted observability) is an always-on Fargate task + internal ALB — pure
    // overhead for a minimal demo/early-prod env, so it only deploys when minimalSpec is off.
    let langfuseService: ecsPatterns.ApplicationLoadBalancedFargateService | undefined;
    if (deployLangfuse) {
    const langfuseTask = new ecs.FargateTaskDefinition(this, "LangfuseTaskDefinition", {
      family: `${servicePrefix}-langfuse`,
      cpu: 1024,
      memoryLimitMiB: 2048,
      runtimePlatform: {
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
        cpuArchitecture: ecs.CpuArchitecture.X86_64
      }
    });
    this.attachRuntimePolicies(langfuseTask.taskRole, documentBucket, dataKey);
    langfuseSecret.grantRead(langfuseTask.taskRole);
    database.secret?.grantRead(langfuseTask.taskRole);

    const langfuseContainer = langfuseTask.addContainer("LangfuseContainer", {
      image: ecs.ContainerImage.fromRegistry("ghcr.io/langfuse/langfuse:2"),
      essential: true,
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: "langfuse",
        logRetention: logs.RetentionDays.ONE_MONTH
      }),
      environment: {
        NODE_ENV: "production",
        TELEMETRY_ENABLED: "false",
        LANGFUSE_LOG_RAW_CONTEXT: "false",
        DATABASE_HOST: database.clusterEndpoint.hostname,
        DATABASE_PORT: database.clusterEndpoint.port.toString(),
        DATABASE_NAME: "raku_rag"
      },
      secrets: {
        NEXTAUTH_SECRET: ecs.Secret.fromSecretsManager(langfuseSecret, "nextauthSecret"),
        DATABASE_PASSWORD: ecs.Secret.fromSecretsManager(database.secret!, "password")
      }
    });
    langfuseContainer.addPortMappings({ containerPort: 3000 });

    langfuseService = new ecsPatterns.ApplicationLoadBalancedFargateService(
      this,
      "LangfuseService",
      {
        cluster,
        taskDefinition: langfuseTask,
        serviceName: `${servicePrefix}-langfuse`,
        publicLoadBalancer: false,
        listenerPort: 3000,
        desiredCount: 1,
        minHealthyPercent: 100,
        circuitBreaker: { rollback: true },
        assignPublicIp: false,
        securityGroups: [ecsSecurityGroup],
        taskSubnets: {
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS
        },
        healthCheckGracePeriod: cdk.Duration.seconds(120)
      }
    );
    langfuseService.targetGroup.configureHealthCheck({
      path: "/api/public/health",
      healthyHttpCodes: "200-399"
    });
    }

    const frontendHosting = props.frontendHosting ?? "external-vercel";
    if (frontendHosting === "aws-nextjs") {
      this.addAwsNextjsFallback(
        servicePrefix,
        props.stageName,
        cluster,
        ecsSecurityGroup,
        userPool,
        userPoolClient,
        appSecret
      );
    }

    const apiTarget5xxMetric = apiService.targetGroup.metrics.httpCodeTarget(
      elbv2.HttpCodeTarget.TARGET_5XX_COUNT,
      { period: cdk.Duration.minutes(5), statistic: "Sum" }
    );
    const dlqVisibleMetric = deadLetterQueue.metricApproximateNumberOfMessagesVisible({
      period: cdk.Duration.minutes(5),
      statistic: "Maximum"
    });
    const ingestionQueueAgeMetric = ingestionQueue.metricApproximateAgeOfOldestMessage({
      period: cdk.Duration.minutes(5),
      statistic: "Maximum"
    });
    const auroraCpuMetric = database.metricCPUUtilization({
      period: cdk.Duration.minutes(5),
      statistic: "Average"
    });
    const wafAllowedMetric = this.wafMetric(`${servicePrefix}-api-web-acl`, "AllowedRequests", "ALL");
    const wafBlockedMetric = this.wafMetric(`${servicePrefix}-api-web-acl`, "BlockedRequests", "ALL");
    const wafIpRateLimitBlocks = this.wafMetric(
      `${servicePrefix}-api-web-acl`,
      "BlockedRequests",
      "IpRateLimit"
    );
    const wafUserTokenRateLimitBlocks = this.wafMetric(
      `${servicePrefix}-api-web-acl`,
      "BlockedRequests",
      "UserTokenRateLimit"
    );

    const apiTarget5xxAlarm = new cloudwatch.Alarm(this, "ApiTarget5xxAlarm", {
      alarmName: `${servicePrefix}-api-target-5xx`,
      alarmDescription:
        "SEV-2: NestJS API target 5xx responses exceeded the release runbook threshold.",
      metric: apiTarget5xxMetric,
      threshold: isProd ? 5 : 1,
      evaluationPeriods: 1,
      datapointsToAlarm: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING
    });
    const dlqVisibleAlarm = new cloudwatch.Alarm(this, "IngestionDlqVisibleAlarm", {
      alarmName: `${servicePrefix}-ingestion-dlq-visible`,
      alarmDescription:
        "SEV-2: ingestion messages reached the DLQ; inspect failed document processing before release.",
      metric: dlqVisibleMetric,
      threshold: 1,
      evaluationPeriods: 1,
      datapointsToAlarm: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING
    });
    const ingestionQueueAgeAlarm = new cloudwatch.Alarm(this, "IngestionQueueAgeAlarm", {
      alarmName: `${servicePrefix}-ingestion-queue-age`,
      alarmDescription:
        "SEV-3: ingestion queue age exceeded the freshness budget; scale workers or pause intake.",
      metric: ingestionQueueAgeMetric,
      threshold: isProd ? 900 : 1800,
      evaluationPeriods: 2,
      datapointsToAlarm: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING
    });
    const auroraCpuAlarm = new cloudwatch.Alarm(this, "AuroraCpuAlarm", {
      alarmName: `${servicePrefix}-aurora-cpu-high`,
      alarmDescription:
        "SEV-3: Aurora pgvector CPU is high; inspect vector query plans and ingestion load.",
      metric: auroraCpuMetric,
      threshold: 80,
      evaluationPeriods: 3,
      datapointsToAlarm: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING
    });
    const wafRateLimitAlarm = new cloudwatch.Alarm(this, "ApiWafRateLimitBlockedAlarm", {
      alarmName: `${servicePrefix}-api-waf-rate-limit-blocks`,
      alarmDescription:
        "SEV-3: API WAF rate-limit blocks exceeded the abuse threshold; inspect token/IP sources.",
      metric: new cloudwatch.MathExpression({
        expression: "ip + token",
        usingMetrics: {
          ip: wafIpRateLimitBlocks,
          token: wafUserTokenRateLimitBlocks
        },
        period: cdk.Duration.minutes(5)
      }),
      threshold: isProd ? 100 : 10,
      evaluationPeriods: 1,
      datapointsToAlarm: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING
    });

    const dashboard = new cloudwatch.Dashboard(this, "OperationsDashboard", {
      dashboardName: `${servicePrefix}-operations`
    });
    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "ECS CPU utilization",
        left: [
          apiService.service.metricCpuUtilization(),
          workerService.metricCpuUtilization(),
          ...(langfuseService ? [langfuseService.service.metricCpuUtilization()] : [])
        ]
      }),
      new cloudwatch.GraphWidget({
        title: "Aurora Serverless v2 pgvector",
        left: [auroraCpuMetric, database.metricDatabaseConnections()]
      }),
      new cloudwatch.GraphWidget({
        title: "SQS ingestion queues",
        left: [
          ingestionQueue.metricApproximateNumberOfMessagesVisible(),
          dlqVisibleMetric,
          ingestionQueueAgeMetric
        ]
      }),
      new cloudwatch.GraphWidget({
        title: "API load balancer target errors",
        left: [apiTarget5xxMetric]
      }),
      new cloudwatch.GraphWidget({
        title: "API WAF allowed vs blocked requests",
        left: [wafAllowedMetric, wafBlockedMetric]
      }),
      new cloudwatch.GraphWidget({
        title: "API WAF rate-limit blocks",
        left: [wafIpRateLimitBlocks, wafUserTokenRateLimitBlocks]
      })
    );

    new cdk.CfnOutput(this, "ApiLoadBalancerDnsName", {
      value: apiService.loadBalancer.loadBalancerDnsName
    });
    if (langfuseService) {
      new cdk.CfnOutput(this, "LangfuseInternalLoadBalancerDnsName", {
        value: langfuseService.loadBalancer.loadBalancerDnsName
      });
    }
    new cdk.CfnOutput(this, "AnswerServiceInternalLoadBalancerDnsName", {
      value: answerService.loadBalancer.loadBalancerDnsName
    });
    new cdk.CfnOutput(this, "DocumentBucketName", {
      value: documentBucket.bucketName
    });
    new cdk.CfnOutput(this, "IngestionQueueUrl", {
      value: ingestionQueue.queueUrl
    });
    new cdk.CfnOutput(this, "AuroraEndpoint", {
      value: database.clusterEndpoint.socketAddress
    });
    new cdk.CfnOutput(this, "PgvectorExtensionSql", {
      value: pgvectorExtensionSql
    });
    new cdk.CfnOutput(this, "CognitoUserPoolId", {
      value: userPool.userPoolId
    });
    new cdk.CfnOutput(this, "CloudWatchDashboardName", {
      value: dashboard.dashboardName
    });
    new cdk.CfnOutput(this, "CloudWatchAlarmNames", {
      value: [
        apiTarget5xxAlarm.alarmName,
        dlqVisibleAlarm.alarmName,
        ingestionQueueAgeAlarm.alarmName,
        auroraCpuAlarm.alarmName,
        wafRateLimitAlarm.alarmName
      ].join(",")
    });
    new cdk.CfnOutput(this, "ApiWebAclArn", {
      value: apiWebAcl.attrArn
    });
    new cdk.CfnOutput(this, "FrontendHostingMode", {
      value: frontendHosting
    });
  }

  private wafVisibilityConfig(metricName: string): wafv2.CfnWebACL.VisibilityConfigProperty {
    return {
      cloudWatchMetricsEnabled: true,
      metricName,
      sampledRequestsEnabled: true
    };
  }

  private wafMetric(webAclName: string, metricName: string, rule: string): cloudwatch.Metric {
    return new cloudwatch.Metric({
      namespace: "AWS/WAFV2",
      metricName,
      dimensionsMap: {
        WebACL: webAclName,
        Rule: rule,
        Region: cdk.Aws.REGION
      },
      statistic: "Sum"
    });
  }

  private attachRuntimePolicies(
    taskRole: iam.IRole,
    documentBucket: s3.IBucket,
    dataKey: kms.IKey
  ): void {
    documentBucket.grantReadWrite(taskRole);
    dataKey.grantEncryptDecrypt(taskRole);
  }

  // Allow a task role to invoke Bedrock foundation models (the #1 semantic-embeddings + Claude
  // generation path). Inert until RAKU_RUNTIME_PROFILE=production wires the real providers; scoped to
  // InvokeModel on Bedrock model resources.
  private grantBedrockInvoke(taskRole: iam.IRole): void {
    taskRole.addToPrincipalPolicy(
      new iam.PolicyStatement({
        actions: ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
        resources: [
          `arn:aws:bedrock:*::foundation-model/*`,
          `arn:aws:bedrock:*:${cdk.Stack.of(this).account}:inference-profile/*`
        ]
      })
    );
  }

  private addAwsNextjsFallback(
    servicePrefix: string,
    stageName: string,
    cluster: ecs.ICluster,
    ecsSecurityGroup: ec2.ISecurityGroup,
    userPool: cognito.IUserPool,
    userPoolClient: cognito.IUserPoolClient,
    appSecret: secretsmanager.ISecret
  ): ecsPatterns.ApplicationLoadBalancedFargateService {
    const task = new ecs.FargateTaskDefinition(this, "AwsNextjsTaskDefinition", {
      family: `${servicePrefix}-web`,
      cpu: 512,
      memoryLimitMiB: 1024,
      runtimePlatform: {
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
        cpuArchitecture: ecs.CpuArchitecture.X86_64
      }
    });
    appSecret.grantRead(task.taskRole);

    const container = task.addContainer("AwsNextjsContainer", {
      image: ecs.ContainerImage.fromRegistry("public.ecr.aws/docker/library/node:20-alpine"),
      command: ["sh", "-c", "node --version && sleep infinity"],
      essential: true,
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: "web",
        logRetention: logs.RetentionDays.ONE_MONTH
      }),
      environment: {
        NODE_ENV: "production",
        STAGE_NAME: stageName,
        COGNITO_USER_POOL_ID: userPool.userPoolId,
        COGNITO_USER_POOL_CLIENT_ID: userPoolClient.userPoolClientId,
        FRONTEND_TELEMETRY_RAW_CONTEXT: "false"
      },
      secrets: {
        APPLICATION_SECRET: ecs.Secret.fromSecretsManager(appSecret)
      }
    });
    container.addPortMappings({ containerPort: 3000 });

    return new ecsPatterns.ApplicationLoadBalancedFargateService(this, "AwsNextjsService", {
      cluster,
      taskDefinition: task,
      serviceName: `${servicePrefix}-web`,
      publicLoadBalancer: true,
      listenerPort: 80,
      desiredCount: 1,
      minHealthyPercent: 100,
      circuitBreaker: { rollback: true },
      assignPublicIp: false,
      securityGroups: [ecsSecurityGroup],
      taskSubnets: {
        subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS
      },
      healthCheckGracePeriod: cdk.Duration.seconds(60)
    });
  }
}
