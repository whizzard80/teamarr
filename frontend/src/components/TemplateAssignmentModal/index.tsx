/**
 * TemplateAssignmentModal — manage template assignments for multi-league groups.
 *
 * Allows assigning different templates based on sport/league filters:
 * - leagues match (most specific) → sports match → default (fallback)
 */

import { useState, useCallback, useEffect, useMemo } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Select } from "@/components/ui/select"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { CheckboxListPicker } from "@/components/ui/checkbox-list-picker"
import type { CheckboxListGroup } from "@/components/ui/checkbox-list-picker"
import {
  getGroupTemplates,
  addGroupTemplate,
  updateGroupTemplate,
  deleteGroupTemplate,
  bulkSetGroupTemplates,
} from "@/api/groups"
import type { GroupTemplate, BulkTemplateAssignment } from "@/api/groups"
import { useTemplates } from "@/hooks/useTemplates"
import { useSports } from "@/hooks/useSports"
import { getLeagues } from "@/api/teams"
import { getSportDisplayName } from "@/lib/utils"
import { Loader2, Plus, Pencil, Trash2, Layers } from "lucide-react"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

// Local assignment type for new groups (no database ID yet)
export interface LocalTemplateAssignment {
  template_id: number
  sports: string[] | null
  leagues: string[] | null
  template_name?: string
}

interface TemplateAssignmentModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  groupId?: number // Optional - if not provided, uses local mode
  groupName: string
  groupLeagues: string[] // Leagues configured in this group
  // Local mode props (for new groups before saving)
  localAssignments?: LocalTemplateAssignment[]
  onLocalChange?: (assignments: LocalTemplateAssignment[]) => void
  // Bulk mode props (for applying to multiple groups)
  bulkGroupIds?: number[] // If provided, enables bulk mode
  onBulkComplete?: () => void // Called after bulk apply succeeds
}

interface EditingAssignment {
  id?: number // undefined for new, number for edit
  template_id: number | null
  sports: string[]
  leagues: string[]
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TemplateAssignmentModal({
  open,
  onOpenChange,
  groupId,
  groupName,
  groupLeagues,
  localAssignments,
  onLocalChange,
  bulkGroupIds,
  onBulkComplete,
}: TemplateAssignmentModalProps) {
  const queryClient = useQueryClient()

  // Determine mode:
  // - bulk mode: bulkGroupIds provided (applying to multiple groups)
  // - local mode: no groupId (new group, not saved yet)
  // - database mode: groupId provided (editing single existing group)
  const isBulkMode = bulkGroupIds && bulkGroupIds.length > 0
  const isLocalMode = !groupId && !isBulkMode

  // Bulk mode uses local state for assignments (starts empty)
  const [bulkAssignments, setBulkAssignments] = useState<LocalTemplateAssignment[]>([])

  // Form state for add/edit
  const [editing, setEditing] = useState<EditingAssignment | null>(null)

  // Fetch current assignments (only in database mode - single group editing)
  const {
    data: dbAssignments,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["groupTemplates", groupId],
    queryFn: () => getGroupTemplates(groupId!),
    enabled: open && !isLocalMode && !isBulkMode,
  })

  // Determine which assignments to show based on mode
  const assignments = isBulkMode
    ? bulkAssignments.map((a, idx) => ({
        id: idx + 1, // Temporary ID for bulk assignments
        group_id: 0,
        template_id: a.template_id,
        sports: a.sports,
        leagues: a.leagues,
        template_name: a.template_name ?? null,
      }))
    : isLocalMode
    ? localAssignments?.map((a, idx) => ({
        id: idx + 1, // Temporary ID for local assignments
        group_id: 0,
        template_id: a.template_id,
        sports: a.sports,
        leagues: a.leagues,
        template_name: a.template_name ?? null,
      }))
    : dbAssignments

  // Fetch templates for dropdown
  const { data: templates } = useTemplates()
  const eventTemplates = templates?.filter((t) => t.template_type === "event") || []

  // Fetch sports for dropdown
  const { data: sportsData } = useSports()
  const sportsMap = sportsData?.sports || {}

  // Fetch leagues for display
  const { data: leaguesData } = useQuery({
    queryKey: ["leagues"],
    queryFn: () => getLeagues(),
    enabled: open,
  })
  const allLeagues = leaguesData?.leagues || []

  // Get unique sports from group's leagues (sorted)
  const groupSports = useMemo(() =>
    [...new Set(
      allLeagues
        .filter((l) => groupLeagues.includes(l.slug))
        .map((l) => l.sport)
    )].sort(),
    [allLeagues, groupLeagues]
  )

  // Build sport items for CheckboxListPicker (flat mode)
  const sportItems = useMemo(() =>
    groupSports.map((sport) => ({
      value: sport,
      label: getSportDisplayName(sport, sportsMap),
    })),
    [groupSports, sportsMap]
  )

  // Build league groups for CheckboxListPicker (grouped mode)
  const leagueGroups: CheckboxListGroup[] = useMemo(() => {
    const grouped: Record<string, { slug: string; name: string; sport: string }[]> = {}
    for (const slug of groupLeagues) {
      const league = allLeagues.find((l) => l.slug === slug)
      const sport = league?.sport || "other"
      if (!grouped[sport]) grouped[sport] = []
      grouped[sport].push({ slug, name: league?.name || slug, sport })
    }
    return Object.keys(grouped)
      .sort()
      .map((sport) => ({
        key: sport,
        label: getSportDisplayName(sport, sportsMap),
        items: grouped[sport]
          .sort((a, b) => a.name.localeCompare(b.name))
          .map((l) => ({ value: l.slug, label: l.name })),
      }))
  }, [groupLeagues, allLeagues, sportsMap])

  // Mutations (only used when not in local mode)
  const addMutation = useMutation({
    mutationFn: (data: { template_id: number; sports?: string[]; leagues?: string[] }) =>
      addGroupTemplate(groupId!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["groupTemplates", groupId] })
      setEditing(null)
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({
      assignmentId,
      data,
    }: {
      assignmentId: number
      data: { template_id?: number; sports?: string[]; leagues?: string[] }
    }) => updateGroupTemplate(groupId!, assignmentId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["groupTemplates", groupId] })
      setEditing(null)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (assignmentId: number) => deleteGroupTemplate(groupId!, assignmentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["groupTemplates", groupId] })
    },
  })

  // Bulk mutation - apply assignments to all selected groups
  const bulkMutation = useMutation({
    mutationFn: (assignments: BulkTemplateAssignment[]) =>
      bulkSetGroupTemplates({
        group_ids: bulkGroupIds!,
        assignments,
      }),
    onSuccess: () => {
      // Invalidate all affected groups
      bulkGroupIds?.forEach((id) => {
        queryClient.invalidateQueries({ queryKey: ["groupTemplates", id] })
      })
      queryClient.invalidateQueries({ queryKey: ["groups"] })
      onBulkComplete?.()
      onOpenChange(false)
    },
  })

  // Reset state when modal closes
  useEffect(() => {
    if (!open) {
      setEditing(null)
      setBulkAssignments([])
    }
  }, [open])

  const handleAdd = useCallback(() => {
    setEditing({
      template_id: null,
      sports: [],
      leagues: [],
    })
  }, [])

  const handleEdit = useCallback((assignment: GroupTemplate) => {
    setEditing({
      id: assignment.id,
      template_id: assignment.template_id,
      sports: assignment.sports || [],
      leagues: assignment.leagues || [],
    })
  }, [])

  const handleDelete = useCallback(
    (assignmentId: number) => {
      if (confirm("Delete this template assignment?")) {
        if (isBulkMode) {
          // In bulk mode, remove from bulk state (assignmentId is index + 1)
          setBulkAssignments((prev) => prev.filter((_, idx) => idx + 1 !== assignmentId))
        } else if (isLocalMode && onLocalChange && localAssignments) {
          // In local mode, remove from local state (assignmentId is index + 1)
          const newAssignments = localAssignments.filter((_, idx) => idx + 1 !== assignmentId)
          onLocalChange(newAssignments)
        } else {
          deleteMutation.mutate(assignmentId)
        }
      }
    },
    [deleteMutation, isBulkMode, isLocalMode, onLocalChange, localAssignments]
  )

  const handleSave = useCallback(() => {
    if (!editing || !editing.template_id) return

    const templateName = eventTemplates.find((t) => t.id === editing.template_id)?.name

    const newAssignment: LocalTemplateAssignment = {
      template_id: editing.template_id,
      sports: editing.sports.length > 0 ? editing.sports : null,
      leagues: editing.leagues.length > 0 ? editing.leagues : null,
      template_name: templateName,
    }

    if (isBulkMode) {
      // In bulk mode, update bulk state
      if (editing.id) {
        // Edit existing (editing.id is index + 1)
        setBulkAssignments((prev) => {
          const updated = [...prev]
          updated[editing.id! - 1] = newAssignment
          return updated
        })
      } else {
        // Add new
        setBulkAssignments((prev) => [...prev, newAssignment])
      }
      setEditing(null)
    } else if (isLocalMode && onLocalChange) {
      // In local mode, update local state
      if (editing.id && localAssignments) {
        // Edit existing (editing.id is index + 1)
        const newAssignments = [...localAssignments]
        newAssignments[editing.id - 1] = newAssignment
        onLocalChange(newAssignments)
      } else {
        // Add new
        onLocalChange([...(localAssignments || []), newAssignment])
      }
      setEditing(null)
    } else {
      // Database mode
      const data = {
        template_id: editing.template_id,
        sports: editing.sports.length > 0 ? editing.sports : undefined,
        leagues: editing.leagues.length > 0 ? editing.leagues : undefined,
      }

      if (editing.id) {
        updateMutation.mutate({ assignmentId: editing.id, data })
      } else {
        addMutation.mutate(data)
      }
    }
  }, [editing, addMutation, updateMutation, isBulkMode, isLocalMode, onLocalChange, localAssignments, eventTemplates])

  const handleCancel = useCallback(() => {
    setEditing(null)
  }, [])

  // Apply bulk assignments to all selected groups
  const handleBulkApply = useCallback(() => {
    if (!isBulkMode || bulkAssignments.length === 0) return

    const assignments: BulkTemplateAssignment[] = bulkAssignments.map((a) => ({
      template_id: a.template_id,
      sports: a.sports,
      leagues: a.leagues,
    }))

    bulkMutation.mutate(assignments)
  }, [isBulkMode, bulkAssignments, bulkMutation])

  // --- Selection change handlers for CheckboxListPicker ---
  const handleSportsChange = useCallback((sports: string[]) => {
    setEditing((prev) => prev ? { ...prev, sports } : null)
  }, [])

  const handleLeaguesChange = useCallback((leagues: string[]) => {
    setEditing((prev) => prev ? { ...prev, leagues } : null)
  }, [])


  const getSpecificityLabel = (assignment: GroupTemplate) => {
    if (assignment.leagues && assignment.leagues.length > 0) {
      return "League"
    }
    if (assignment.sports && assignment.sports.length > 0) {
      return "Sport"
    }
    return "Default"
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Layers className="h-4 w-4" />
            {isBulkMode
              ? `Template Assignments (${bulkGroupIds?.length} groups)`
              : "Template Assignments"}
          </DialogTitle>
          <DialogDescription>
            {isBulkMode
              ? "Configure template assignments to apply to all selected groups. This will replace any existing assignments."
              : `Assign templates to ${groupName} by sport or league. More specific matches take priority.`}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Bulk mode warning */}
          {isBulkMode && (
            <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-3 text-sm text-amber-600 dark:text-amber-400">
              <strong>Note:</strong> Applying these assignments will replace all existing template
              assignments on the {bulkGroupIds?.length} selected groups.
            </div>
          )}

          {/* Current assignments */}
          {isLoading && (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          )}

          {error && (
            <div className="text-sm text-destructive py-4">
              Failed to load template assignments.
            </div>
          )}

          {!isLoading && !error && (
            <>
              {/* Assignments table */}
              {assignments && assignments.length > 0 ? (
                <div className="border rounded-lg overflow-hidden">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/50">
                      <tr>
                        <th className="text-left px-3 py-2 font-medium">Template</th>
                        <th className="text-left px-3 py-2 font-medium">Filter</th>
                        <th className="text-left px-3 py-2 font-medium">Specificity</th>
                        <th className="text-right px-3 py-2 font-medium w-24">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {assignments.map((a) => (
                        <tr key={a.id} className="border-t">
                          <td className="px-3 py-2">{a.template_name || `Template ${a.template_id}`}</td>
                          <td className="px-3 py-2">
                            <div className="flex flex-wrap gap-1">
                              {a.leagues?.map((l) => (
                                <Badge key={l} variant="secondary" className="text-xs">
                                  {allLeagues.find((lg) => lg.slug === l)?.name || l}
                                </Badge>
                              ))}
                              {a.sports?.map((s) => (
                                <Badge key={s} variant="outline" className="text-xs">
                                  {sportsMap[s] || s}
                                </Badge>
                              ))}
                              {!a.leagues?.length && !a.sports?.length && (
                                <span className="text-muted-foreground text-xs">All events</span>
                              )}
                            </div>
                          </td>
                          <td className="px-3 py-2">
                            <Badge
                              variant={
                                getSpecificityLabel(a) === "League"
                                  ? "default"
                                  : getSpecificityLabel(a) === "Sport"
                                  ? "secondary"
                                  : "outline"
                              }
                              className="text-xs"
                            >
                              {getSpecificityLabel(a)}
                            </Badge>
                          </td>
                          <td className="px-3 py-2 text-right">
                            <div className="flex justify-end gap-1">
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 w-7 p-0"
                                onClick={() => handleEdit(a)}
                              >
                                <Pencil className="h-3.5 w-3.5" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                                onClick={() => handleDelete(a.id)}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="text-center py-8 text-muted-foreground text-sm">
                  No template assignments yet. Add one to get started.
                </div>
              )}

              {/* Add/Edit form */}
              {editing && (
                <div className="border rounded-lg p-4 space-y-4 bg-muted/30">
                  <h4 className="font-medium text-sm">
                    {editing.id ? "Edit Assignment" : "New Assignment"}
                  </h4>

                  {/* Template select */}
                  <div className="space-y-2">
                    <Label>Template</Label>
                    <Select
                      value={editing.template_id?.toString() || ""}
                      onChange={(e) =>
                        setEditing({
                          ...editing,
                          template_id: e.target.value ? Number(e.target.value) : null,
                        })
                      }
                    >
                      <option value="">Select template...</option>
                      {eventTemplates.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.name}
                        </option>
                      ))}
                    </Select>
                  </div>

                  {/* Sports filter */}
                  {groupSports.length > 1 && (
                    <div className="space-y-2">
                      <Label>Sports (optional — leave empty for all)</Label>
                      <CheckboxListPicker
                        selected={editing.sports}
                        onChange={handleSportsChange}
                        items={sportItems}
                        searchPlaceholder="Search sports..."
                        maxHeight="max-h-36"
                      />
                    </div>
                  )}

                  {/* Leagues filter */}
                  <div className="space-y-2">
                    <Label>Leagues (optional — leave empty for all)</Label>
                    <CheckboxListPicker
                      selected={editing.leagues}
                      onChange={handleLeaguesChange}
                      groups={leagueGroups}
                      searchPlaceholder="Search leagues..."
                      maxHeight="max-h-48"
                    />
                  </div>

                  {/* Form actions */}
                  <div className="flex justify-end gap-2 pt-2">
                    <Button variant="outline" size="sm" onClick={handleCancel}>
                      Cancel
                    </Button>
                    <Button
                      size="sm"
                      onClick={handleSave}
                      disabled={!editing.template_id || addMutation.isPending || updateMutation.isPending}
                    >
                      {addMutation.isPending || updateMutation.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin mr-1" />
                      ) : null}
                      {editing.id ? "Update" : "Add"}
                    </Button>
                  </div>
                </div>
              )}

              {/* Add button */}
              {!editing && (
                <Button variant="outline" size="sm" onClick={handleAdd} className="w-full">
                  <Plus className="h-4 w-4 mr-1" />
                  Add Template Assignment
                </Button>
              )}
            </>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {isBulkMode ? "Cancel" : "Done"}
          </Button>
          {isBulkMode && (
            <Button
              onClick={handleBulkApply}
              disabled={bulkAssignments.length === 0 || bulkMutation.isPending}
            >
              {bulkMutation.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Apply to {bulkGroupIds?.length} Groups
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
