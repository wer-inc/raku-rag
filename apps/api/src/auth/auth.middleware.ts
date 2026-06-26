import { Injectable, NestMiddleware, UnauthorizedException } from "@nestjs/common";
import type { Request, Response, NextFunction } from "express";
import { parseCognitoJwt } from "./cognito";
import { parseUserToken, type Principal } from "./principal";

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      principal?: Principal;
    }
  }
}

export function authMode(): "dev" | "cognito" {
  const raw = (process.env.RAKU_AUTH_MODE || "").trim().toLowerCase();
  if (raw === "dev" || raw === "cognito") {
    return raw;
  }
  return process.env.NODE_ENV === "production" ? "cognito" : "dev";
}

function bearerToken(req: Request): string {
  const auth = req.header("authorization") ?? "";
  if (!auth.toLowerCase().startsWith("bearer ") || auth.slice(7).trim() === "") {
    throw new UnauthorizedException("missing bearer token");
  }
  return auth.slice(7).trim();
}

/**
 * Production auth boundary.
 *
 * - `RAKU_AUTH_MODE=cognito`: verifies Cognito RS256 JWTs via JWKS; tenant/user/roles are derived
 *   from signed claims only.
 * - `RAKU_AUTH_MODE=dev`: preserves the local HMAC `X-User-Token` path for demos/tests.
 */
@Injectable()
export class AuthMiddleware implements NestMiddleware {
  async use(req: Request, _res: Response, next: NextFunction) {
    const mode = authMode();
    if (mode === "dev") {
      bearerToken(req);
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
      return;
    }

    if (req.header("x-user-token")) {
      throw new UnauthorizedException("X-User-Token is disabled in Cognito auth mode");
    }
    const principal = await parseCognitoJwt(bearerToken(req), {
      issuer: process.env.COGNITO_ISSUER ?? "",
      clientId: process.env.COGNITO_CLIENT_ID ?? process.env.COGNITO_USER_POOL_CLIENT_ID ?? "",
      jwksUri: process.env.COGNITO_JWKS_URI,
    });
    if (!principal) {
      throw new UnauthorizedException("invalid Cognito JWT");
    }
    req.principal = principal;
    next();
  }
}
