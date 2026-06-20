import { Injectable, NestMiddleware, UnauthorizedException } from "@nestjs/common";
import type { Request, Response, NextFunction } from "express";
import { parseUserToken, type Principal } from "./principal";

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      principal?: Principal;
    }
  }
}

/**
 * P0-T06 / Step 4 — local auth middleware (no Cognito yet). Requires an
 * `Authorization: Bearer <api-key>` and an HMAC-signed `X-User-Token`; attaches the verified principal
 * to the request. Production swaps in Cognito/JWKS behind this boundary.
 */
@Injectable()
export class AuthMiddleware implements NestMiddleware {
  use(req: Request, _res: Response, next: NextFunction) {
    const auth = req.header("authorization") ?? "";
    if (!auth.toLowerCase().startsWith("bearer ") || auth.slice(7).trim() === "") {
      throw new UnauthorizedException("missing API key");
    }
    const userToken = req.header("x-user-token");
    if (!userToken) {
      throw new UnauthorizedException("missing X-User-Token");
    }
    const principal = parseUserToken(userToken);
    if (!principal) {
      throw new UnauthorizedException("invalid X-User-Token");
    }
    req.principal = principal;
    next();
  }
}
