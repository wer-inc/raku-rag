import { Controller, Get, Req } from "@nestjs/common";
import type { Request } from "express";

// Protected route used by the e2e tests to prove the auth middleware attached the principal
// and the tenant context is available.
@Controller({ path: "whoami", version: "1" })
export class WhoamiController {
  @Get()
  whoami(@Req() req: Request) {
    return { principal: req.principal ?? null };
  }
}
