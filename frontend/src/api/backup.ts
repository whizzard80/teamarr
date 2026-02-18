/**
 * Backup and restore API functions
 */

import { api } from "./client"

// =============================================================================
// TYPES
// =============================================================================

export interface RestoreResponse {
  success: boolean
  message: string
  backup_path: string | null
}

export interface BackupInfo {
  filename: string
  filepath: string
  size_bytes: number
  created_at: string
  is_protected: boolean
  backup_type: "scheduled" | "manual"
}

export interface BackupListResponse {
  backups: BackupInfo[]
  total: number
}

export interface BackupCreateResponse {
  success: boolean
  filename: string | null
  filepath: string | null
  size_bytes: number | null
  error: string | null
}

export interface BackupDeleteResponse {
  success: boolean
  message: string
}

export interface BackupProtectResponse {
  success: boolean
  is_protected: boolean
}

export interface BackupSettings {
  enabled: boolean
  cron: string
  max_count: number
  path: string
}

export interface BackupSettingsUpdate {
  enabled?: boolean
  cron?: string
  max_count?: number
  path?: string
}

// =============================================================================
// LEGACY BACKUP/RESTORE FUNCTIONS
// =============================================================================

/**
 * Download a backup of the database (legacy endpoint).
 * Opens the download in a new tab/triggers browser download.
 */
export function downloadBackup(): void {
  // Use direct URL for file download (not fetch)
  window.location.href = "/api/v1/backup"
}

/**
 * Restore database from uploaded backup file.
 */
export async function restoreBackup(file: File): Promise<RestoreResponse> {
  const formData = new FormData()
  formData.append("file", file)

  const response = await fetch("/api/v1/backup", {
    method: "POST",
    body: formData,
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || "Failed to restore backup")
  }

  return response.json()
}

// =============================================================================
// BACKUP MANAGEMENT FUNCTIONS
// =============================================================================

/**
 * List all backup files.
 */
export async function listBackups(): Promise<BackupListResponse> {
  return api.get("/backup/list")
}

/**
 * Create a manual backup.
 */
export async function createBackup(): Promise<BackupCreateResponse> {
  return api.post("/backup/create")
}

/**
 * Delete a backup file.
 */
export async function deleteBackup(filename: string): Promise<BackupDeleteResponse> {
  return api.delete(`/backup/${encodeURIComponent(filename)}`)
}

/**
 * Protect a backup from rotation deletion.
 */
export async function protectBackup(filename: string): Promise<BackupProtectResponse> {
  return api.post(`/backup/${encodeURIComponent(filename)}/protect`)
}

/**
 * Remove protection from a backup.
 */
export async function unprotectBackup(filename: string): Promise<BackupProtectResponse> {
  return api.post(`/backup/${encodeURIComponent(filename)}/unprotect`)
}

/**
 * Restore database from an existing backup file.
 */
export async function restoreFromBackup(filename: string): Promise<RestoreResponse> {
  return api.post(`/backup/${encodeURIComponent(filename)}/restore`)
}

/**
 * Get download URL for a specific backup file.
 */
export function getBackupDownloadUrl(filename: string): string {
  return `/api/v1/backup/file/${encodeURIComponent(filename)}`
}

/**
 * Download a specific backup file.
 */
export function downloadSpecificBackup(filename: string): void {
  window.location.href = getBackupDownloadUrl(filename)
}

// =============================================================================
// BACKUP SETTINGS FUNCTIONS
// =============================================================================

/**
 * Get scheduled backup settings.
 */
export async function getBackupSettings(): Promise<BackupSettings> {
  return api.get("/backup/settings")
}

/**
 * Update scheduled backup settings.
 */
export async function updateBackupSettings(
  data: BackupSettingsUpdate
): Promise<BackupSettings> {
  return api.put("/backup/settings", data)
}
