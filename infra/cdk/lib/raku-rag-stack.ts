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
import { Construct } from "constructs";

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
      readers: [
        rds.ClusterInstance.serverlessV2("reader", {
          scaleWithWriter: true,
          publiclyAccessible: false
        })
      ],
      serverlessV2MinCapacity: 0.5,
      serverlessV2MaxCapacity: 4,
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
      cpu: 1024,
      memoryLimitMiB: 2048,
      runtimePlatform: {
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
        cpuArchitecture: ecs.CpuArchitecture.X86_64
      }
    });
    this.attachRuntimePolicies(apiTask.taskRole, documentBucket, dataKey);
    ingestionQueue.grantSendMessages(apiTask.taskRole);
    appSecret.grantRead(apiTask.taskRole);
    database.secret?.grantRead(apiTask.taskRole);

    const apiContainer = apiTask.addContainer("NestjsApiContainer", {
      image: ecs.ContainerImage.fromRegistry("public.ecr.aws/docker/library/node:20-alpine"),
      command: ["sh", "-c", "node --version && sleep infinity"],
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

    const workerTask = new ecs.FargateTaskDefinition(this, "PythonWorkerTaskDefinition", {
      family: `${servicePrefix}-worker`,
      cpu: 512,
      memoryLimitMiB: 1024,
      runtimePlatform: {
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
        cpuArchitecture: ecs.CpuArchitecture.X86_64
      }
    });
    this.attachRuntimePolicies(workerTask.taskRole, documentBucket, dataKey);
    ingestionQueue.grantConsumeMessages(workerTask.taskRole);
    database.secret?.grantRead(workerTask.taskRole);

    workerTask.addContainer("PythonIngestWorkerContainer", {
      image: ecs.ContainerImage.fromRegistry("public.ecr.aws/docker/library/python:3.12-slim"),
      command: ["python", "-m", "workers.ingest.worker", "--drain"],
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

    const langfuseService = new ecsPatterns.ApplicationLoadBalancedFargateService(
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

    const dashboard = new cloudwatch.Dashboard(this, "OperationsDashboard", {
      dashboardName: `${servicePrefix}-operations`
    });
    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "ECS CPU utilization",
        left: [
          apiService.service.metricCpuUtilization(),
          workerService.metricCpuUtilization(),
          langfuseService.service.metricCpuUtilization()
        ]
      }),
      new cloudwatch.GraphWidget({
        title: "Aurora Serverless v2 pgvector",
        left: [database.metricCPUUtilization(), database.metricDatabaseConnections()]
      }),
      new cloudwatch.GraphWidget({
        title: "SQS ingestion queues",
        left: [
          ingestionQueue.metricApproximateNumberOfMessagesVisible(),
          deadLetterQueue.metricApproximateNumberOfMessagesVisible()
        ]
      }),
      new cloudwatch.GraphWidget({
        title: "API load balancer target errors",
        left: [
          apiService.targetGroup.metrics.httpCodeTarget(elbv2.HttpCodeTarget.TARGET_5XX_COUNT)
        ]
      })
    );

    new cdk.CfnOutput(this, "ApiLoadBalancerDnsName", {
      value: apiService.loadBalancer.loadBalancerDnsName
    });
    new cdk.CfnOutput(this, "LangfuseInternalLoadBalancerDnsName", {
      value: langfuseService.loadBalancer.loadBalancerDnsName
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
    new cdk.CfnOutput(this, "FrontendHostingMode", {
      value: frontendHosting
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
