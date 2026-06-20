#!/usr/bin/env node
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const controllerPath = path.resolve(__dirname, "../src/openapi/openapi.controller.ts");
const source = fs.readFileSync(controllerPath, "utf8");
const match = source.match(/const OPENAPI_DOC = ([\s\S]*?) as const;\n\n@Controller/);

if (!match) {
  console.error("OPENAPI_DOC literal not found");
  process.exit(1);
}

const script = new vm.Script(`(${match[1]})`, { filename: "openapi.controller.ts" });
const doc = script.runInNewContext({});
process.stdout.write(JSON.stringify(doc, null, 2));
process.stdout.write("\n");
