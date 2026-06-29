export interface BoundingBoxDto {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface AssetRegion {
  region_id: string;
  chunk_id: string;
  region_type: string;
  page_number: number;
  bbox: BoundingBoxDto;
  crop_uri: string;
  crop_url?: string;
}

export interface AssetCrop {
  crop_id: string;
  asset_id: string;
  region_id: string;
  crop_uri: string;
  crop_url?: string;
  bbox: BoundingBoxDto;
  redaction_policy_ref: string;
}

export interface VisualAssetResponse {
  asset_id: string;
  tenant_id: string;
  collection_id: string;
  document_id: string;
  source_id: string;
  version: number;
  storage_uri: string;
  content_type: string;
  page_number: number;
  regions: AssetRegion[];
  crops: AssetCrop[];
}
