import { api } from "./client"
import type {
  BulkGroupUpdateRequest,
  BulkGroupUpdateResponse,
  EventGroup,
  EventGroupCreate,
  EventGroupListResponse,
  EventGroupUpdate,
  PreviewGroupResponse,
} from "./types"

export async function listGroups(
  includeDisabled = false,
  includeStats = true
): Promise<EventGroupListResponse> {
  const params = new URLSearchParams()
  if (includeDisabled) params.set("include_disabled", "true")
  if (includeStats) params.set("include_stats", "true")
  return api.get(`/groups?${params}`)
}

export async function getGroup(groupId: number): Promise<EventGroup> {
  return api.get(`/groups/${groupId}`)
}

export async function createGroup(data: EventGroupCreate): Promise<EventGroup> {
  return api.post("/groups", data)
}

export async function updateGroup(
  groupId: number,
  data: EventGroupUpdate
): Promise<EventGroup> {
  return api.put(`/groups/${groupId}`, data)
}

export async function deleteGroup(
  groupId: number
): Promise<{ success: boolean; message: string; channels_deleted: number }> {
  return api.delete(`/groups/${groupId}`)
}

export async function enableGroup(
  groupId: number
): Promise<{ success: boolean; message: string }> {
  return api.post(`/groups/${groupId}/enable`)
}

export async function disableGroup(
  groupId: number
): Promise<{ success: boolean; message: string }> {
  return api.post(`/groups/${groupId}/disable`)
}

export interface PromoteGroupResponse {
  success: boolean
  promoted_group_id: number
  promoted_group_name: string
  old_parent_id: number
  old_parent_name: string
  reassigned_groups: number[]
  message: string
}

export async function promoteGroup(
  groupId: number
): Promise<PromoteGroupResponse> {
  return api.post(`/groups/${groupId}/promote`)
}

export async function previewGroup(
  groupId: number
): Promise<PreviewGroupResponse> {
  return api.get(`/groups/${groupId}/preview`)
}

export interface RawStream {
  stream_id: number
  stream_name: string
  /** Reason stream would be filtered by builtin filters (null if passes) */
  builtin_filtered: string | null
}

export interface RawStreamsResponse {
  group_id: number
  group_name: string
  total: number
  streams: RawStream[]
}

export async function getRawStreams(
  groupId: number
): Promise<RawStreamsResponse> {
  return api.get(`/groups/${groupId}/streams/raw`)
}

export async function reorderGroups(
  groups: { group_id: number; sort_order: number }[]
): Promise<{ success: boolean; updated_count: number; message: string }> {
  return api.post("/groups/reorder", { groups })
}

export async function bulkUpdateGroups(
  data: BulkGroupUpdateRequest
): Promise<BulkGroupUpdateResponse> {
  return api.put("/groups/bulk", data)
}

export interface ClearCacheResponse {
  success: boolean
  group_id?: number
  group_name?: string
  entries_cleared?: number
  total_cleared?: number
  by_group?: { group_id: number; cleared: number }[]
}

export async function clearGroupMatchCache(
  groupId: number
): Promise<ClearCacheResponse> {
  return api.post(`/groups/${groupId}/cache/clear`)
}

export async function clearGroupsMatchCache(
  groupIds: number[]
): Promise<ClearCacheResponse> {
  return api.post("/groups/cache/clear", { group_ids: groupIds })
}

// =============================================================================
// Group Templates - Multi-template assignment per group
// =============================================================================

export interface GroupTemplate {
  id: number
  group_id: number
  template_id: number
  sports: string[] | null
  leagues: string[] | null
  template_name: string | null
}

export interface GroupTemplateCreate {
  template_id: number
  sports?: string[]
  leagues?: string[]
}

export interface GroupTemplateUpdate {
  template_id?: number
  sports?: string[]
  leagues?: string[]
}

export async function getGroupTemplates(
  groupId: number
): Promise<GroupTemplate[]> {
  return api.get(`/groups/${groupId}/templates`)
}

export async function addGroupTemplate(
  groupId: number,
  data: GroupTemplateCreate
): Promise<GroupTemplate> {
  return api.post(`/groups/${groupId}/templates`, data)
}

export async function updateGroupTemplate(
  groupId: number,
  assignmentId: number,
  data: GroupTemplateUpdate
): Promise<GroupTemplate> {
  return api.put(`/groups/${groupId}/templates/${assignmentId}`, data)
}

export async function deleteGroupTemplate(
  groupId: number,
  assignmentId: number
): Promise<void> {
  return api.delete(`/groups/${groupId}/templates/${assignmentId}`)
}

// Bulk template assignment for multiple groups
export interface BulkTemplateAssignment {
  template_id: number
  sports?: string[] | null
  leagues?: string[] | null
}

export interface BulkTemplatesRequest {
  group_ids: number[]
  assignments: BulkTemplateAssignment[]
}

export interface BulkTemplatesResponse {
  success: boolean
  groups_updated: number
  assignments_per_group: number
  message: string
}

export async function bulkSetGroupTemplates(
  data: BulkTemplatesRequest
): Promise<BulkTemplatesResponse> {
  return api.put("/groups/bulk-templates", data)
}
