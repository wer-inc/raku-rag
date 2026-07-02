import { BadRequestException, Body, Controller, HttpCode, Post, Req } from "@nestjs/common";
import type { Request } from "express";
import type { UploadRegisterRequest, UploadRegisterResponse } from "@raku-rag/shared";
import { PhoneForwardingService } from "../phone/phone.service";
import { assertDocumentRefOwnedByTenant } from "./s3-ref-ownership";

/**
 * 0045 — S3 upload provenance registration. The web presign route calls this BEFORE handing the
 * browser a presigned PUT URL; ingest later resolves `upload_id` -> (bucket, key) from the stored
 * record instead of trusting a caller-supplied raw `s3://` ref. Thin proxy: identity from the
 * signed principal only; the answer-service owns the record.
 */
@Controller({ path: "uploads", version: "1" })
export class UploadsController {
  private readonly forwarding = new PhoneForwardingService();

  @Post()
  @HttpCode(201)
  async register(
    @Req() req: Request,
    @Body() body: UploadRegisterRequest,
  ): Promise<UploadRegisterResponse> {
    const p = req.principal!;
    if (!body?.upload_id || !body?.bucket || !body?.object_key) {
      throw new BadRequestException("upload_id, bucket and object_key are required");
    }
    // Same bucket-allowlist + tenant-prefix wall as ingest: a record may only ever point at an
    // object this tenant could legitimately have presigned.
    assertDocumentRefOwnedByTenant(`s3://${body.bucket}/${body.object_key}`, p.tenant_id);
    return this.forwarding.forward(req, "POST", "/internal/uploads", body);
  }
}
