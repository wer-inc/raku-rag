-- Visual provider-policy allowlists for production OCR/layout/structured/caption/VLM paths.
SET search_path TO public;

ALTER TABLE provider_policies
  ADD COLUMN IF NOT EXISTS allowed_layout_providers text[] NOT NULL DEFAULT ARRAY['aws_textract','tesseract','customer_managed']::text[],
  ADD COLUMN IF NOT EXISTS allowed_structured_providers text[] NOT NULL DEFAULT ARRAY['aws_textract','customer_managed']::text[],
  ADD COLUMN IF NOT EXISTS allowed_visual_embedding_providers text[] NOT NULL DEFAULT ARRAY['bedrock','customer_managed']::text[],
  ADD COLUMN IF NOT EXISTS allowed_vlm_providers text[] NOT NULL DEFAULT ARRAY['bedrock','customer_managed']::text[],
  ADD COLUMN IF NOT EXISTS allowed_caption_providers text[] NOT NULL DEFAULT ARRAY['bedrock','customer_managed']::text[],
  ADD COLUMN IF NOT EXISTS opt_in_status_by_family jsonb NOT NULL DEFAULT '{}'::jsonb;
