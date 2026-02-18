import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  listBackups,
  createBackup,
  deleteBackup,
  protectBackup,
  unprotectBackup,
  restoreFromBackup,
  getBackupSettings,
  updateBackupSettings,
} from "@/api/backup"
import type { BackupSettingsUpdate } from "@/api/backup"

/**
 * Hook to list all backup files.
 */
export function useBackups() {
  return useQuery({
    queryKey: ["backups"],
    queryFn: listBackups,
  })
}

/**
 * Hook to create a manual backup.
 */
export function useCreateBackup() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: createBackup,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["backups"] })
    },
  })
}

/**
 * Hook to delete a backup file.
 */
export function useDeleteBackup() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (filename: string) => deleteBackup(filename),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["backups"] })
    },
  })
}

/**
 * Hook to protect a backup from rotation.
 */
export function useProtectBackup() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (filename: string) => protectBackup(filename),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["backups"] })
    },
  })
}

/**
 * Hook to unprotect a backup.
 */
export function useUnprotectBackup() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (filename: string) => unprotectBackup(filename),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["backups"] })
    },
  })
}

/**
 * Hook to restore from an existing backup file.
 */
export function useRestoreFromBackup() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (filename: string) => restoreFromBackup(filename),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["backups"] })
    },
  })
}

/**
 * Hook to get backup settings.
 */
export function useBackupSettings() {
  return useQuery({
    queryKey: ["settings", "backup"],
    queryFn: getBackupSettings,
  })
}

/**
 * Hook to update backup settings.
 */
export function useUpdateBackupSettings() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: BackupSettingsUpdate) => updateBackupSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings", "backup"] })
      queryClient.invalidateQueries({ queryKey: ["settings"] })
    },
  })
}
