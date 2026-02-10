import { useEffect, useState } from "react"

type Theme = "dark" | "light"

/**
 * Hook to get the current theme.
 * Syncs with localStorage and DOM class changes.
 */
export function useTheme(): Theme {
  const [theme, setTheme] = useState<Theme>(() => {
    // Check localStorage first
    const saved = localStorage.getItem("theme")
    if (saved === "dark" || saved === "light") return saved
    // Fall back to DOM class
    return document.documentElement.classList.contains("dark") ? "dark" : "light"
  })

  useEffect(() => {
    // Listen for theme changes via storage event (cross-tab sync)
    const handleStorage = (e: StorageEvent) => {
      if (e.key === "theme" && (e.newValue === "dark" || e.newValue === "light")) {
        setTheme(e.newValue)
      }
    }

    // Also observe DOM class changes for same-tab updates
    const observer = new MutationObserver(() => {
      const isDark = document.documentElement.classList.contains("dark")
      setTheme(isDark ? "dark" : "light")
    })

    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    })

    window.addEventListener("storage", handleStorage)
    return () => {
      window.removeEventListener("storage", handleStorage)
      observer.disconnect()
    }
  }, [])

  return theme
}

/**
 * Get the appropriate logo URL based on current theme.
 * Falls back to primary logo if dark variant doesn't exist.
 */
export function useThemedLogo(
  logoUrl: string | null | undefined,
  logoUrlDark: string | null | undefined
): string | null {
  const theme = useTheme()

  if (!logoUrl && !logoUrlDark) return null

  if (theme === "dark" && logoUrlDark) {
    return logoUrlDark
  }

  return logoUrl || logoUrlDark || null
}

