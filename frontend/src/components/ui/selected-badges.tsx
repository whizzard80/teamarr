import { X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { RichTooltip } from "@/components/ui/rich-tooltip"

export interface BadgeItem {
  key: string
  label: string
  icon?: string
}

interface SelectedBadgesProps {
  items: BadgeItem[]
  maxBadges?: number
  onRemove: (key: string) => void
}

export function SelectedBadges({
  items,
  maxBadges = 10,
  onRemove,
}: SelectedBadgesProps) {
  if (items.length === 0) return null

  return (
    <div className="flex flex-wrap gap-1">
      {items.slice(0, maxBadges).map((item) => (
        <Badge key={item.key} variant="secondary" className="gap-1">
          {item.icon && (
            <img src={item.icon} alt="" className="h-3 w-3 object-contain" />
          )}
          {item.label}
          <button onClick={() => onRemove(item.key)} className="ml-1 hover:bg-muted rounded">
            <X className="h-3 w-3" />
          </button>
        </Badge>
      ))}
      {items.length > maxBadges && (
        <RichTooltip
          content={
            <div className="text-xs space-y-0.5 max-h-48 overflow-y-auto">
              {items.slice(maxBadges).map((item) => (
                <div key={item.key}>{item.label}</div>
              ))}
            </div>
          }
        >
          <Badge variant="outline" className="cursor-help">+{items.length - maxBadges} more</Badge>
        </RichTooltip>
      )}
    </div>
  )
}
