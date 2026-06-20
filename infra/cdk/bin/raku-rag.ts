#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { FrontendHostingMode, RakuRagStack } from "../lib/raku-rag-stack";

const app = new cdk.App();
const stageName = app.node.tryGetContext("stage") ?? "dev";
const frontendHosting = (app.node.tryGetContext("frontendHosting") ??
  "external-vercel") as FrontendHostingMode;

new RakuRagStack(app, `RakuRag-${stageName}`, {
  stageName,
  frontendHosting,
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION ?? "us-east-1"
  }
});
