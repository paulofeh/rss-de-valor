export interface Env {
  PRIVATE_FEEDS_BUCKET: R2Bucket;
  BASIC_AUTH_USERNAME: string;
  BASIC_AUTH_PASSWORD_CURRENT: string;
  BASIC_AUTH_USERNAME_NEXT?: string;
  BASIC_AUTH_PASSWORD_NEXT?: string;
}

export interface CurrentPointer {
  schema_version: 1;
  run_id: string;
  manifest_key: string;
  manifest_sha256: string;
  published_at: string;
}

export interface SnapshotObject {
  key: string;
  content_type: string;
  size: number;
  sha256: string;
  last_modified: string;
}

export interface SnapshotRoute {
  object_path: string;
}

export interface SnapshotManifest {
  schema_version: 1;
  run_id: string;
  created_at: string;
  source_revision: string;
  canary_path: string;
  counts: {
    feeds: number;
    history_files: number;
    metadata_files: number;
    objects: number;
    routes: number;
  };
  objects: Record<string, SnapshotObject>;
  routes: Record<string, SnapshotRoute>;
}

declare global {
  namespace Cloudflare {
    interface Env {
      PRIVATE_FEEDS_BUCKET: R2Bucket;
      BASIC_AUTH_USERNAME: string;
      BASIC_AUTH_PASSWORD_CURRENT: string;
      BASIC_AUTH_USERNAME_NEXT?: string;
      BASIC_AUTH_PASSWORD_NEXT?: string;
    }
  }
}
