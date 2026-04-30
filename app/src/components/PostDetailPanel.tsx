/**
 * PostDetailPanel — shown in the sidebar when a post is selected on the map.
 *
 * Shows: post name, formation, altitude, current status pill, kerosene
 * stock + daily burn + days-to-stockout, the authored note (if today is
 * an anchor day), and provenance grade.
 *
 * The "click any number, see its source" feature comes in Wk9. For Wk8
 * we just render the numbers cleanly.
 */
import type { Post } from "@/types";
import type { PostStateSnapshot } from "@/lib/scenarioEngine";
import { StatusPill } from "./StatusPill";

interface PostDetailPanelProps {
  post: Post;
  snapshot: PostStateSnapshot | undefined;
  onClose: () => void;
}

export function PostDetailPanel({ post, snapshot, onClose }: PostDetailPanelProps) {
  return (
    <div className="border-t border-line bg-canvas">
      <div className="flex items-start justify-between border-b border-line p-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wider text-ink-faint">
            Selection · {post.post_id}
          </div>
          <div className="mt-1 text-sm font-semibold text-ink">{post.name}</div>
          <div className="text-xs text-ink-muted">
            {post.sub_sector.replace(/_/g, " ")} · {post.notional_formation}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-xs text-ink-faint hover:text-ink-muted"
          aria-label="Close detail panel"
        >
          ✕
        </button>
      </div>

      <div className="space-y-3 p-4">
        <Row
          label="Altitude"
          value={`${post.altitude_m.toLocaleString()} m · ${post.altitude_band}`}
        />
        <Row label="Type" value={post.type.replace(/_/g, " ")} />
        <Row label="Primary depot" value={post.primary_depot} />
        <Row
          label="Provenance"
          value={
            <span className="font-mono text-xs">
              {post.provenance_grade}
            </span>
          }
        />

        {snapshot && (
          <>
            <hr className="my-2 border-line" />
            <div className="flex items-baseline justify-between">
              <span className="text-xs font-medium text-ink-muted">Status</span>
              <StatusPill status={snapshot.status} />
            </div>

            {snapshot.kerosene_stock_L !== null && (
              <Row
                label="Kerosene stock"
                value={`${snapshot.kerosene_stock_L.toLocaleString()} L`}
              />
            )}
            {snapshot.daily_burn_L !== null && (
              <Row
                label="Daily burn"
                value={`${Math.round(snapshot.daily_burn_L).toLocaleString()} L/day`}
              />
            )}
            {snapshot.days_to_stockout !== null && (
              <Row
                label="Days to stockout"
                value={
                  <span className="font-mono">
                    {snapshot.days_to_stockout}
                  </span>
                }
              />
            )}

            {snapshot.note && (
              <div className="mt-2 rounded border border-line bg-surface p-2 text-xs leading-snug text-ink-muted">
                {snapshot.is_anchor_day && (
                  <span className="mr-1 font-semibold text-ink">
                    Authored note:
                  </span>
                )}
                {snapshot.note}
              </div>
            )}
          </>
        )}

        {!snapshot && (
          <div className="rounded border border-line bg-surface p-2 text-xs text-ink-muted">
            This scenario does not track this post directly. Status is
            inferred from the depot and route layer only.
          </div>
        )}

        <hr className="my-2 border-line" />
        <div className="text-xs leading-snug text-ink-muted">
          <span className="font-medium text-ink">Profile:</span>{" "}
          {post.consumption_profile_hint}
        </div>
      </div>
    </div>
  );
}

function Row({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-xs font-medium text-ink-muted">{label}</span>
      <span className="text-right text-sm text-ink">{value}</span>
    </div>
  );
}
