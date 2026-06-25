import {
  BadGatewayException,
  BadRequestException,
  Body,
  Controller,
  Get,
  HttpCode,
  Post,
  Query,
  Req,
} from "@nestjs/common";
import type { Request } from "express";
import { assertAdminMutationAllowed } from "../auth/roles";
import { internalAuthHeaders } from "../auth/internal-auth";

interface OAuthAuthorizeResponse {
  authorization_url: string;
}

interface OAuthCallbackRequest {
  code: string;
  state: string;
  redirect_uri?: string;
}

interface OAuthCallbackResponse {
  connection_id: string;
  refresh_token_stored: boolean;
}

/**
 * Google OAuth for the Drive connector — a STATELESS relay.
 *
 * The API builds the consent URL (needs only the public client_id) and forwards the callback to the
 * Python answer-service, which holds the client_secret + SecretStore and performs the actual
 * code->token exchange. The API never sees or stores client_secret, codes, or tokens beyond the
 * one-hop relay. Identity flows via the signed X-User-Token (principal headers); body tenant_id is
 * irrelevant (the answer-service takes tenant from x-raku-tenant-id).
 */
@Controller({ path: "oauth", version: "1" })
export class OAuthController {
  private baseUrl(): string {
    return process.env.ANSWER_SERVICE_URL ?? "http://127.0.0.1:8088";
  }

  private redirectUri(override?: string): string {
    return (
      override ||
      process.env.GOOGLE_OAUTH_REDIRECT_URI ||
      "http://localhost:3002/api/oauth/google/callback"
    );
  }

  private principalHeaders(req: Request): Record<string, string> {
    const p = req.principal!;
    return {
      "x-raku-tenant-id": p.tenant_id,
      "x-raku-user-id": p.user_id,
      "x-raku-groups": JSON.stringify(p.groups),
      "x-raku-roles": JSON.stringify(p.roles),
      ...internalAuthHeaders(),
    };
  }

  @Get("google/authorize")
  authorizeGoogle(
    @Req() _req: Request,
    @Query("state") state?: string,
    @Query("redirect_uri") redirectUri?: string,
  ): OAuthAuthorizeResponse {
    // state is the frontend CSRF nonce; it is echoed back and validated client-side against
    // sessionStorage on return. (A signed/expiring server-issued state is a hardening follow-up.)
    if (!state) {
      throw new BadRequestException("state is required");
    }
    const clientId = process.env.GOOGLE_OAUTH_CLIENT_ID;
    if (!clientId) {
      throw new BadGatewayException("Google OAuth is not configured (GOOGLE_OAUTH_CLIENT_ID unset)");
    }
    const scope = process.env.GOOGLE_OAUTH_SCOPES || "https://www.googleapis.com/auth/drive.readonly";
    const url = new URL("https://accounts.google.com/o/oauth2/v2/auth");
    url.searchParams.set("client_id", clientId);
    url.searchParams.set("redirect_uri", this.redirectUri(redirectUri));
    url.searchParams.set("response_type", "code");
    url.searchParams.set("scope", scope);
    url.searchParams.set("access_type", "offline"); // request a refresh token
    url.searchParams.set("prompt", "consent"); // force refresh-token issuance on re-consent
    url.searchParams.set("include_granted_scopes", "true");
    url.searchParams.set("state", state);
    return { authorization_url: url.toString() };
  }

  @Post("google/callback")
  @HttpCode(200)
  async callbackGoogle(
    @Req() req: Request,
    @Body() body: OAuthCallbackRequest,
  ): Promise<OAuthCallbackResponse> {
    // Connecting a datasource credential is an admin mutation.
    assertAdminMutationAllowed(req);
    if (!body?.code || !body?.state) {
      throw new BadRequestException("code and state are required");
    }
    const headers: Record<string, string> = {
      ...this.principalHeaders(req),
      "content-type": "application/json",
    };
    const upstream = await fetch(`${this.baseUrl()}/internal/oauth/google/callback`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        code: body.code,
        redirect_uri: this.redirectUri(body.redirect_uri),
        provider: "google_drive",
      }),
    }).catch(() => {
      throw new BadGatewayException("answer-service unreachable");
    });
    if (!upstream.ok) {
      throw new BadGatewayException(`answer-service error: ${upstream.status}`);
    }
    const result = (await upstream.json()) as OAuthCallbackResponse;
    return {
      connection_id: result.connection_id,
      refresh_token_stored: Boolean(result.refresh_token_stored),
    };
  }
}
