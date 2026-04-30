/**
 * StatusPill — reusable status indicator. Used in the sidebar list and
 * post detail panel. Map markers use raw color values directly.
 */
import type { PostStatus } from "@/types";

const LABELS: Record<PostStatus, string> = {
  ok: "OK",
  watch: "Watch",
  critical: "Critical",
  imminent: "Imminent",
};

const CLASS_MAP: Record<PostStatus, { bg: string; text: string; dot: string }> = {
  ok: { bg: "bg-status-ok-soft", text: "text-status-ok", dot: "bg-status-ok" },
  watch: { bg: "bg-status-watch-soft", text: "text-status-watch", dot: "bg-status-watch" },
  critical: {
    bg: "bg-status-critical-soft",
    text: "text-status-critical",
    dot: "bg-status-critical",
  },
  imminent: {
    bg: "bg-status-imminent-soft",
    text: "text-status-imminent",
    dot: "bg-status-imminent",
  },
};

export function StatusPill({
  status,
  size = "md",
}: {
  status: PostStatus;
  size?: "sm" | "md";
}) {
  const c = CLASS_MAP[status];
  const sizing =
    size === "sm"
      ? "px-1.5 py-0.5 text-xs gap-1"
      : "px-2 py-0.5 text-xs gap-1.5";
  return (
    <span
      className={`inline-flex items-center rounded-full font-medium ${c.bg} ${c.text} ${sizing}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${c.dot}`} />
      {LABELS[status]}
    </span>
  );
}

/**
 * Raw hex colors for map markers — Tailwind classes don't render inside
 * MapLibre marker DOM (they're outside the React tree). Keep in sync
 * with tailwind.config.js if those colors change.
 */
export const STATUS_HEX: Record<PostStatus, string> = {
  ok: "#16a34a",
  watch: "#ca8a04",
  critical: "#dc2626",
  imminent: "#991b1b",
};
