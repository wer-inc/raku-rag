SET search_path TO public;

ALTER TABLE provider_policies
  DROP COLUMN IF EXISTS opt_in_status_by_family,
  DROP COLUMN IF EXISTS allowed_caption_providers,
  DROP COLUMN IF EXISTS allowed_vlm_providers,
  DROP COLUMN IF EXISTS allowed_visual_embedding_providers,
  DROP COLUMN IF EXISTS allowed_structured_providers,
  DROP COLUMN IF EXISTS allowed_layout_providers;
