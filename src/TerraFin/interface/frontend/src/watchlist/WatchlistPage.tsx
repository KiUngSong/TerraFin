import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  DndContext,
  closestCenter,
  PointerSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import type { DragEndEvent } from '@dnd-kit/core';
import {
  SortableContext,
  horizontalListSortingStrategy,
  verticalListSortingStrategy,
  useSortable,
  arrayMove,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import DashboardHeader from '../dashboard/components/DashboardHeader';
import InsightCard from '../dashboard/components/InsightCard';
import { BREAKPOINTS } from '../shared/responsive';
import TickerSearchInput from '../shared/TickerSearchInput';
import { WatchlistItem, useWatchlist } from './useWatchlist';

const NARROW_LAYOUT_BREAKPOINT = BREAKPOINTS.TABLET_MAX + 157; // 1180

// Reserved tag — drives realtime monitor registration on the backend, not a
// user-managed group. Hidden from group lists / cross-group pill display.
const MONITOR_TAG = 'monitor';
const RESERVED_TAGS = new Set([MONITOR_TAG]);

const isReservedTag = (tag: string): boolean => RESERVED_TAGS.has(tag.toLowerCase());

// ─── Helpers ─────────────────────────────────────────────────────────────────

function nextDefaultGroupName(existingNames: string[]): string {
  const lower = new Set(existingNames.map((n) => n.toLowerCase()));
  let n = 1;
  while (lower.has(`base group ${n}`)) n++;
  return `Base Group ${n}`;
}

function moveColor(move: string): string {
  if (!move || move === '--' || move === '-') return '#94a3b8';
  return move.startsWith('-') ? '#b91c1c' : '#047857';
}

interface GroupDropdownProps {
  value: string;
  options: string[];
  onChange: (value: string) => void;
  disabled?: boolean;
}

const GroupDropdown: React.FC<GroupDropdownProps> = ({ value, options, onChange, disabled }) => {
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  return (
    <div ref={wrapperRef} style={{ position: 'relative', width: '100%' }}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        style={groupDropdownButtonStyle(disabled ?? false)}
      >
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {value || 'Select group'}
        </span>
        <span style={{ marginLeft: 8, color: '#64748b', fontSize: 10 }}>▼</span>
      </button>
      {open && (
        <ul style={groupDropdownListStyle}>
          {options.map((opt) => (
            <li key={opt}>
              <button
                type="button"
                onClick={() => {
                  onChange(opt);
                  setOpen(false);
                }}
                style={groupDropdownItemStyle(opt === value)}
              >
                {opt}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

interface DisplayGroup {
  name: string;
  items: WatchlistItem[];
  isSynthetic: boolean;
}

function buildDisplayGroups(
  items: WatchlistItem[],
  groupTags: string[],
): DisplayGroup[] {
  const result: DisplayGroup[] = groupTags.map((tag) => ({
    name: tag,
    items: items.filter((item) => item.tags.includes(tag)),
    isSynthetic: false,
  }));

  const untagged = items.filter((item) => item.tags.length === 0);
  if (untagged.length > 0) {
    const syntheticName = nextDefaultGroupName(groupTags);
    result.unshift({ name: syntheticName, items: untagged, isSynthetic: true });
  }

  if (result.length === 0) {
    result.push({ name: 'Base Group 1', items: [], isSynthetic: true });
  }

  return result;
}

// ─── Sortable group tab ───────────────────────────────────────────────────────

interface SortableGroupTabProps {
  id: string;
  group: DisplayGroup;
  isActive: boolean;
  isReorderMode: boolean;
  onClick: () => void;
}

const SortableGroupTab: React.FC<SortableGroupTabProps> = ({ id, group, isActive, isReorderMode, onClick }) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id,
    disabled: !isReorderMode || group.isSynthetic,
  });
  return (
    <div
      ref={setNodeRef}
      style={{
        flexShrink: 0,
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.4 : 1,
        cursor: isReorderMode && !group.isSynthetic ? 'grab' : undefined,
        touchAction: isReorderMode && !group.isSynthetic ? 'none' : undefined,
      }}
      {...(isReorderMode && !group.isSynthetic ? { ...attributes, ...listeners } : {})}
    >
      <button
        type="button"
        onClick={() => { if (!isReorderMode || group.isSynthetic) onClick(); }}
        style={{
          ...tabStyle(isActive),
          opacity: isReorderMode && group.isSynthetic ? 0.5 : 1,
        }}
      >
        {isReorderMode && !group.isSynthetic && (
          <span style={{ marginRight: 4, color: '#94a3b8', fontSize: 11 }}>⠿</span>
        )}
        {group.name}
        <span style={{ marginLeft: 5, fontSize: 11, opacity: 0.65 }}>
          {group.items.length}
        </span>
      </button>
    </div>
  );
};

// ─── Sortable ticker row ──────────────────────────────────────────────────────

interface SortableTickerRowProps {
  id: string;
  item: WatchlistItem;
  canDrag: boolean;
  isNarrowLayout: boolean;
  activeGroup: string | null;
  groupTags: string[];
  backendConfigured: boolean;
  monitorEnabled: boolean;
  busy: boolean;
  assigningTickerFor: string | null;
  activeDisplayGroup: DisplayGroup | null;
  onRemove: (symbol: string, group: string | undefined) => void;
  onSetTags: (symbol: string, tags: string[], mode: 'set' | 'add' | 'remove') => void;
  onAssign: (symbol: string | null) => void;
}

const SortableTickerRow: React.FC<SortableTickerRowProps> = ({
  id, item, canDrag, isNarrowLayout, activeGroup, groupTags,
  backendConfigured, monitorEnabled, busy, assigningTickerFor,
  activeDisplayGroup, onRemove, onSetTags, onAssign,
}) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id,
    disabled: !canDrag,
  });

  const otherGroupTags = item.tags.filter(
    (t) => t !== activeGroup && !isReservedTag(t),
  );
  const availableGroups = groupTags.filter(
    (g) => !item.tags.includes(g) && !isReservedTag(g),
  );
  const isMonitored = item.tags.some((t) => t.toLowerCase() === MONITOR_TAG);

  return (
    <div
      ref={setNodeRef}
      style={{
        ...tickerRowStyle(isNarrowLayout, canDrag),
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.4 : 1,
      }}
    >
      {canDrag && (
        <span
          style={{ color: '#cbd5e1', fontSize: 16, cursor: 'grab', flexShrink: 0, userSelect: 'none', paddingRight: 4, touchAction: 'none' }}
          {...attributes}
          {...listeners}
        >⠿</span>
      )}
      <div style={{ minWidth: 0, flex: 1 }}>
        <a href={`/stock/${item.symbol}`} style={symbolLinkStyle}>{item.symbol}</a>
        {item.name && item.name !== item.symbol ? (
          <div
            style={{ fontSize: 12, color: '#64748b', marginTop: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
            title={item.name}
          >
            {item.name}
          </div>
        ) : null}
        {(otherGroupTags.length > 0 || (backendConfigured && availableGroups.length > 0)) && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, marginTop: 5, alignItems: 'center' }}>
            {otherGroupTags.map((tag) => (
              <span key={tag} style={{ ...tagPillStyle, display: 'inline-flex', alignItems: 'center', gap: 2 }}>
                {tag}
                {backendConfigured && (
                  <button
                    type="button"
                    title={`Remove from ${tag}`}
                    onClick={() => { onSetTags(item.symbol, [tag], 'remove'); }}
                    disabled={busy}
                    style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, fontSize: 9, color: '#94a3b8', lineHeight: 1 }}
                  >×</button>
                )}
              </span>
            ))}
            {backendConfigured && availableGroups.length > 0 && (
              assigningTickerFor === item.symbol ? (
                <select
                  autoFocus
                  defaultValue=""
                  onChange={(e) => {
                    if (e.target.value) { onSetTags(item.symbol, [e.target.value], 'add'); }
                    onAssign(null);
                  }}
                  onBlur={() => onAssign(null)}
                  style={{ fontSize: 11, borderRadius: 6, border: '1px solid #cbd5e1', padding: '2px 4px', color: '#475569' }}
                >
                  <option value="" disabled>Add to group…</option>
                  {availableGroups.map((g) => (
                    <option key={g} value={g}>{g}</option>
                  ))}
                </select>
              ) : (
                <button
                  type="button"
                  onClick={() => onAssign(item.symbol)}
                  style={addGroupPillStyle}
                >+ group</button>
              )
            )}
          </div>
        )}
      </div>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0,
        justifyContent: isNarrowLayout ? 'flex-start' : 'flex-end', flexWrap: 'wrap',
      }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: moveColor(item.move) }}>
          {item.move}
        </span>
        {backendConfigured && monitorEnabled ? (
          <button
            type="button"
            onClick={() => { onSetTags(item.symbol, [MONITOR_TAG], isMonitored ? 'remove' : 'add'); }}
            disabled={busy}
            title={isMonitored ? 'Stop realtime monitoring' : 'Start realtime monitoring'}
            aria-pressed={isMonitored}
            style={monitorToggleStyle(isMonitored, busy)}
          >
            <span aria-hidden="true">{isMonitored ? '🔔' : '🔕'}</span>
            <span>{isMonitored ? 'Monitoring' : 'Monitor'}</span>
          </button>
        ) : null}
        {backendConfigured ? (
          <button
            type="button"
            onClick={() => {
              onRemove(item.symbol, activeDisplayGroup && !activeDisplayGroup.isSynthetic ? activeDisplayGroup.name : undefined);
            }}
            disabled={busy}
            style={secondaryButtonStyle(busy)}
          >
            Remove
          </button>
        ) : null}
      </div>
    </div>
  );
};

// ─── Group management panel ───────────────────────────────────────────────────

interface GroupManagePanelProps {
  displayGroups: DisplayGroup[];
  busy: boolean;
  onRename: (group: DisplayGroup, newName: string) => Promise<void>;
  onDelete: (group: DisplayGroup) => Promise<void>;
  onAddGroup: (name: string) => Promise<void>;
  onClose: () => void;
}

const GroupManagePanel: React.FC<GroupManagePanelProps> = ({
  displayGroups,
  busy,
  onRename,
  onDelete,
  onAddGroup,
  onClose,
}) => {
  const [renamingGroup, setRenamingGroup] = useState<string | null>(null);
  const [renameInput, setRenameInput] = useState('');
  const [newGroupInput, setNewGroupInput] = useState('');
  const [confirmDeleteFor, setConfirmDeleteFor] = useState<string | null>(null);
  const renameSubmittedRef = React.useRef(false);

  const startRename = (name: string) => {
    renameSubmittedRef.current = false;
    setRenamingGroup(name);
    setRenameInput(name);
  };

  const confirmRename = async () => {
    if (renameSubmittedRef.current) return;
    renameSubmittedRef.current = true;
    const trimmed = renameInput.trim();
    if (!trimmed || trimmed === renamingGroup) { setRenamingGroup(null); return; }
    const group = displayGroups.find((g) => g.name === renamingGroup);
    setRenamingGroup(null);
    if (group) await onRename(group, trimmed);
  };

  const handleAddGroup = async () => {
    const name = newGroupInput.trim();
    setNewGroupInput('');
    if (!name) return;
    await onAddGroup(name);
  };

  return (
    <div style={panelStyle}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: '#0f172a' }}>Manage Groups</span>
        <button type="button" onClick={onClose} style={panelCloseBtnStyle}>✕</button>
      </div>

      {/* Group list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 14 }}>
        {displayGroups.map((group) => {
          const isRenaming = renamingGroup === group.name;
          const isConfirmingDelete = confirmDeleteFor === group.name;

          return (
            <div key={group.name} style={groupRowStyle}>
              {isRenaming ? (
                <>
                  <input
                    value={renameInput}
                    onChange={(e) => setRenameInput(e.target.value)}
                    onFocus={(e) => e.currentTarget.select()}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') { void confirmRename(); }
                      if (e.key === 'Escape') { renameSubmittedRef.current = true; setRenamingGroup(null); }
                    }}
                    autoFocus
                    style={{ ...panelInputStyle, flex: 1 }}
                  />
                  <button
                    type="button"
                    onClick={() => { void confirmRename(); }}
                    style={{ ...panelActionBtnStyle, color: '#0f172a', borderColor: '#0f172a', flexShrink: 0 }}
                  >Save</button>
                  <button
                    type="button"
                    onClick={() => { renameSubmittedRef.current = true; setRenamingGroup(null); }}
                    style={{ ...panelActionBtnStyle, flexShrink: 0 }}
                  >Cancel</button>
                </>
              ) : (
                <div style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{group.name}</span>
                  {group.items.length === 0 && (
                    <span style={{ fontSize: 10, color: '#94a3b8', marginLeft: 6 }}>empty</span>
                  )}
                </div>
              )}
              <span style={{ fontSize: 11, color: '#94a3b8', marginRight: 8, flexShrink: 0 }}>
                {group.items.length} ticker{group.items.length !== 1 ? 's' : ''}
              </span>
              {!isRenaming && (
                <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                  <button
                    type="button"
                    title="Rename"
                    onClick={() => startRename(group.name)}
                    disabled={busy}
                    style={panelActionBtnStyle}
                  >Rename</button>
                  {isConfirmingDelete ? (
                    <>
                      <button
                        type="button"
                        onClick={() => { void onDelete(group); setConfirmDeleteFor(null); }}
                        disabled={busy}
                        style={{ ...panelActionBtnStyle, color: '#b91c1c', borderColor: '#fca5a5' }}
                      >Confirm</button>
                      <button
                        type="button"
                        onClick={() => setConfirmDeleteFor(null)}
                        style={panelActionBtnStyle}
                      >Cancel</button>
                    </>
                  ) : (
                    <button
                      type="button"
                      title="Delete group"
                      onClick={() => setConfirmDeleteFor(group.name)}
                      disabled={busy}
                      style={panelActionBtnStyle}
                    >Delete</button>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Add new group */}
      <div style={{ display: 'flex', gap: 6, borderTop: '1px solid #f1f5f9', paddingTop: 12 }}>
        <input
          value={newGroupInput}
          onChange={(e) => setNewGroupInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { void handleAddGroup(); } }}
          placeholder="New group name…"
          style={{ ...panelInputStyle, flex: 1 }}
        />
        <button
          type="button"
          onClick={() => { void handleAddGroup(); }}
          disabled={!newGroupInput.trim() || busy}
          style={primaryButtonStyle(!newGroupInput.trim() || busy)}
        >Add</button>
      </div>
    </div>
  );
};

// ─── Main page ───────────────────────────────────────────────────────────────

const WatchlistPage: React.FC = () => {
  const [searchValue, setSearchValue] = useState('');
  const [watchlistInput, setWatchlistInput] = useState('');
  const [isNarrowLayout, setIsNarrowLayout] = useState(false);
  const [activeGroup, setActiveGroup] = useState<string | null>(null);
  const [isManagePanelOpen, setIsManagePanelOpen] = useState(false);
  const [isReorderMode, setIsReorderMode] = useState(false);
  const [itemOrderOverride, setItemOrderOverride] = useState<Record<string, string[]>>({});

  // Separate sensor instances per DndContext to prevent cross-context event routing
  // on touch devices (tab bar context vs item list context).
  const groupSensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 5 } }),
  );
  const itemSensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 5 } }),
  );
  const [assigningTickerFor, setAssigningTickerFor] = useState<string | null>(null);
  const [addToGroup, setAddToGroup] = useState<string | null>(null);

  const {
    items,
    groups,
    loading,
    busy,
    error,
    addSymbol,
    removeSymbol,
    setTags,
    renameGroup,
    createGroup,
    deleteGroup,
    promoteGroup,
    reorderGroups,
    reorderItems,
    backendConfigured,
    monitorEnabled,
  } = useWatchlist();

  const groupTags = useMemo(() => groups.map((g) => g.tag), [groups]);

  const displayGroups = useMemo(
    () => buildDisplayGroups(items, groupTags),
    [items, groupTags],
  );

  // Auto-select first group on load; keep selection when groups change
  useEffect(() => {
    if (displayGroups.length === 0) return;
    setActiveGroup((prev) => {
      if (prev && displayGroups.some((g) => g.name === prev)) return prev;
      return displayGroups[0].name;
    });
  }, [displayGroups]);

  const activeDisplayGroup = useMemo(
    () => displayGroups.find((g) => g.name === activeGroup) ?? displayGroups[0] ?? null,
    [displayGroups, activeGroup],
  );

  const visibleItems = useMemo(() => {
    const base = activeDisplayGroup?.items ?? [];
    const order = activeDisplayGroup ? itemOrderOverride[activeDisplayGroup.name] : undefined;
    if (!order) return base;
    const symMap = Object.fromEntries(base.map((i) => [i.symbol, i]));
    const ordered = order.map((s) => symMap[s]).filter((i): i is WatchlistItem => Boolean(i));
    const extras = base.filter((i) => !order.includes(i.symbol));
    return [...ordered, ...extras];
  }, [activeDisplayGroup, itemOrderOverride]);

  // Keep addToGroup in sync with displayGroups — reset if selected group disappears
  useEffect(() => {
    setAddToGroup((prev) => {
      if (prev && displayGroups.some((g) => g.name === prev)) return prev;
      return displayGroups[0]?.name ?? null;
    });
  }, [displayGroups]);

  const handleAddWatchlistItem = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const symbol = watchlistInput.trim().toUpperCase();
    if (!symbol) return;
    const selectedGroup = displayGroups.find((g) => g.name === addToGroup);
    // Synthetic group = untagged bucket; add ticker with no tags so it lands there
    const tags = selectedGroup?.isSynthetic ? [] : [addToGroup ?? groupTags[0] ?? nextDefaultGroupName(groupTags)];
    try {
      await addSymbol(symbol, tags);
      setWatchlistInput('');
      // Item set changed — stale override would misplace the new ticker
      if (addToGroup) setItemOrderOverride((prev) => { const n = { ...prev }; delete n[addToGroup]; return n; });
    } catch {
      // handled in hook
    }
  };

  const handleGroupDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id || busy) return;
    const oldIdx = displayGroups.findIndex((g) => g.name === active.id);
    const newIdx = displayGroups.findIndex((g) => g.name === over.id);
    if (oldIdx === -1 || newIdx === -1) return;
    const reordered = arrayMove(displayGroups, oldIdx, newIdx);
    void reorderGroups(reordered.filter((g) => !g.isSynthetic).map((g) => g.name));
  };

  const handleItemDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id || !activeDisplayGroup || activeDisplayGroup.isSynthetic) return;
    const oldIdx = visibleItems.findIndex((i) => i.symbol === active.id);
    const newIdx = visibleItems.findIndex((i) => i.symbol === over.id);
    if (oldIdx === -1 || newIdx === -1) return;
    const reordered = arrayMove(visibleItems, oldIdx, newIdx);
    const newOrder = reordered.map((i) => i.symbol);
    const groupName = activeDisplayGroup.name;
    setItemOrderOverride((prev) => ({ ...prev, [groupName]: newOrder }));
    void reorderItems(groupName, newOrder).catch(() => {
      setItemOrderOverride((prev) => {
        const next = { ...prev };
        delete next[groupName];
        return next;
      });
    });
  };

  const handleRenameGroup = async (group: DisplayGroup, newName: string) => {
    const old = group.name;
    const normalized = newName.trim();
    if (!normalized) return;
    if (group.isSynthetic) {
      if (group.items.length === 0) {
        await createGroup(normalized);
        setActiveGroup(normalized);
      } else {
        await promoteGroup(group.items, normalized, items);
        setActiveGroup(normalized);
      }
      return;
    }
    await renameGroup(old, normalized);
    setActiveGroup(normalized);
    // Migrate itemOrderOverride key so drag order persists through rename
    setItemOrderOverride((prev) => {
      if (!(old in prev)) return prev;
      const next = { ...prev };
      next[normalized] = next[old];
      delete next[old];
      return next;
    });
  };

  const handleDeleteGroup = async (group: DisplayGroup) => {
    // Snapshot items before async loop — group.items would be stale after first removeSymbol resolves
    const itemsToDelete = [...group.items];
    if (group.isSynthetic) {
      // Parallel to minimize busy flicker between sequential setBusy(false) calls
      await Promise.all(itemsToDelete.map((item) => removeSymbol(item.symbol)));
    } else {
      await deleteGroup(group.name);
    }
    // No setActiveGroup here — the useEffect on displayGroups already re-selects
    // remaining[0] whenever the deleted group disappears from the list.
  };

  const handleAddNewGroup = async (name: string) => {
    const trimmed = name.trim();
    if (!trimmed) return;
    await createGroup(trimmed);
    setActiveGroup(trimmed);
    setIsManagePanelOpen(false);
  };

  const monitoredCount = useMemo(
    () => items.filter((it) => it.tags.some((t) => t.toLowerCase() === MONITOR_TAG)).length,
    [items],
  );

  const subtitle = useMemo(() => {
    if (items.length === 0) return 'Build a TerraFin watchlist and keep your core tickers in one place.';
    const total = items.length;
    const gc = displayGroups.length;
    const base = `${total} ticker${total !== 1 ? 's' : ''} across ${gc} group${gc !== 1 ? 's' : ''}.`;
    if (!monitorEnabled) return base;
    return `${base} ${monitoredCount} monitored.`;
  }, [items.length, displayGroups.length, monitorEnabled, monitoredCount]);

  useEffect(() => {
    const update = () => setIsNarrowLayout(window.innerWidth < NARROW_LAYOUT_BREAKPOINT);
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);

  return (
    <div style={pageStyle}>
      <DashboardHeader
        searchValue={searchValue}
        onSearchChange={setSearchValue}
        sectionLabel="Watchlist"
        title="TerraFin"
        placeholder="Search ticker or company"
      />

      <main style={{
        display: 'grid',
        gap: 16,
        padding: 16,
        gridTemplateColumns: isNarrowLayout ? '1fr' : 'minmax(300px, 380px) minmax(0, 1fr)',
        alignItems: 'start',
      }}>

        {/* ── Left: management card ── */}
        <InsightCard title="Watchlist" subtitle={subtitle} minHeight={0} allowOverflow>
          <div style={{ display: 'grid', gap: 14 }}>
            {!backendConfigured ? (
              <div style={{ border: '1px solid #cbd5e1', borderRadius: 14, padding: 14, background: '#fff7ed', color: '#9a3412' }}>
                <div style={{ fontSize: 12, fontWeight: 800, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                  Optional Local Backend
                </div>
                <div style={{ marginTop: 6, fontSize: 13, lineHeight: 1.6 }}>
                  Connect MongoDB with <code>TERRAFIN_MONGODB_URI</code> or <code>MONGODB_URI</code> to manage a
                  writable local watchlist. Until then, TerraFin shows a sample watchlist in read-only mode.
                </div>
              </div>
            ) : null}
            <form onSubmit={handleAddWatchlistItem} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto', gap: 8, alignItems: 'center' }}>
                <TickerSearchInput
                  value={watchlistInput}
                  onChange={setWatchlistInput}
                  onSelect={(hit) => setWatchlistInput(hit.symbol)}
                  placeholder="Search ticker or company"
                  ariaLabel="Add ticker to watchlist"
                  inputStyle={inputStyle}
                  disabled={!backendConfigured || busy}
                />
                <button type="submit" disabled={!backendConfigured || busy} style={primaryButtonStyle(!backendConfigured || busy)}>
                  {busy ? '...' : 'Add'}
                </button>
              </div>
              {backendConfigured && displayGroups.length > 0 && (
                <GroupDropdown
                  value={addToGroup ?? ''}
                  options={displayGroups.map((g) => g.name)}
                  onChange={(v) => setAddToGroup(v || null)}
                  disabled={busy}
                />
              )}
            </form>
            {error ? (
              <div style={{ fontSize: 12, color: '#b91c1c' }}>{error}</div>
            ) : null}
          </div>
        </InsightCard>

        {/* ── Right: group tabs + ticker list ── */}
        <InsightCard title="" subtitle="" minHeight={0}>
          {loading ? (
            <div style={{ fontSize: 13, color: '#475569', padding: '8px 0' }}>Loading watchlist...</div>
          ) : (
            <div>
              {/* Tab bar */}
              <div style={{
                ...tabBarWrapperStyle,
                flexDirection: isNarrowLayout ? 'column' : 'row',
                alignItems: isNarrowLayout ? 'stretch' : 'center',
              }}>
                <DndContext sensors={groupSensors} collisionDetection={closestCenter} onDragEnd={handleGroupDragEnd}>
                  <SortableContext items={displayGroups.filter((g) => !g.isSynthetic).map((g) => g.name)} strategy={horizontalListSortingStrategy}>
                    <div style={tabBarStyle}>
                      {displayGroups.map((group) => (
                        <SortableGroupTab
                          key={group.name}
                          id={group.name}
                          group={group}
                          isActive={group.name === activeGroup}
                          isReorderMode={isReorderMode}
                          onClick={() => setActiveGroup(group.name)}
                        />
                      ))}
                    </div>
                  </SortableContext>
                </DndContext>
                {/* Manage + Reorder buttons */}
                {backendConfigured && (
                  <div style={{
                    display: 'flex', gap: 4, flexShrink: 0,
                    marginLeft: isNarrowLayout ? 0 : 8,
                    paddingBottom: isNarrowLayout ? 6 : undefined,
                  }}>
                    <button
                      type="button"
                      onClick={() => { setIsReorderMode((v) => !v); setIsManagePanelOpen(false); }}
                      style={manageTabBtnStyle(isReorderMode)}
                      title={isReorderMode ? 'Done reordering' : 'Reorder groups and tickers'}
                    >{isReorderMode ? 'Done' : '⇅ Reorder'}</button>
                    {!isReorderMode && (
                      <button
                        type="button"
                        onClick={() => setIsManagePanelOpen((v) => !v)}
                        style={manageTabBtnStyle(isManagePanelOpen)}
                        title="Manage groups"
                      >⚙ Manage</button>
                    )}
                  </div>
                )}
              </div>

              {/* Group management panel */}
              {isManagePanelOpen && (
                <GroupManagePanel
                  displayGroups={displayGroups}
                  busy={busy}
                  onRename={handleRenameGroup}
                  onDelete={handleDeleteGroup}
                  onAddGroup={handleAddNewGroup}
                  onClose={() => setIsManagePanelOpen(false)}
                />
              )}

              {/* Ticker list */}
              <DndContext sensors={itemSensors} collisionDetection={closestCenter} onDragEnd={handleItemDragEnd}>
                <SortableContext items={visibleItems.map((i) => i.symbol)} strategy={verticalListSortingStrategy}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 12 }}>
                    {visibleItems.length === 0 ? (
                      <div style={{ fontSize: 13, color: '#94a3b8', padding: '12px 0' }}>
                        No tickers in this group yet. Add one using the form on the left.
                      </div>
                    ) : (
                      visibleItems.map((item, itemIdx) => {
                        const canDrag = !!(isReorderMode && backendConfigured && activeDisplayGroup && !activeDisplayGroup.isSynthetic);
                        return (
                          <SortableTickerRow
                            key={item.symbol}
                            id={item.symbol}
                            item={item}
                            canDrag={canDrag}
                            isNarrowLayout={isNarrowLayout}
                            activeGroup={activeGroup}
                            groupTags={groupTags}
                            backendConfigured={backendConfigured}
                            monitorEnabled={monitorEnabled}
                            busy={busy}
                            assigningTickerFor={assigningTickerFor}
                            activeDisplayGroup={activeDisplayGroup}
                            onRemove={(symbol, group) => {
                              void removeSymbol(symbol, group);
                              // Item set changed — clear stale override so order resets to server truth
                              if (activeDisplayGroup) setItemOrderOverride((prev) => { const n = { ...prev }; delete n[activeDisplayGroup.name]; return n; });
                            }}
                            onSetTags={(symbol, tags, mode) => { void setTags(symbol, tags, mode); }}
                            onAssign={setAssigningTickerFor}
                          />
                        );
                      })
                    )}
                  </div>
                </SortableContext>
              </DndContext>
            </div>
          )}
        </InsightCard>
      </main>
    </div>
  );
};

// ─── Styles ───────────────────────────────────────────────────────────────────

const pageStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  width: '100%',
  height: '100%',
  overflow: 'auto',
  background: 'linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%)',
  fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  color: '#0f172a',
};

const inputStyle: React.CSSProperties = {
  border: '1px solid #cbd5e1',
  borderRadius: 12,
  padding: '11px 14px',
  fontSize: 14,
  color: '#0f172a',
  background: '#ffffff',
  width: '100%',
  boxSizing: 'border-box',
};

const tabBarWrapperStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  borderBottom: '1px solid #e2e8f0',
  gap: 0,
};

const tabBarStyle: React.CSSProperties = {
  display: 'flex',
  flex: 1,
  overflowX: 'auto',
  gap: 0,
  // fade at right edge to hint scrollability
  maskImage: 'linear-gradient(to right, black calc(100% - 24px), transparent 100%)',
  WebkitMaskImage: 'linear-gradient(to right, black calc(100% - 24px), transparent 100%)',
};

const tabStyle = (active: boolean): React.CSSProperties => ({
  flexShrink: 0,
  background: 'none',
  border: 'none',
  borderBottom: active ? '2.5px solid #0f172a' : '2.5px solid transparent',
  padding: '8px 14px',
  fontSize: 13,
  fontWeight: active ? 700 : 500,
  color: active ? '#0f172a' : '#64748b',
  cursor: 'pointer',
  whiteSpace: 'nowrap',
  transition: 'color 0.15s, border-color 0.15s',
});

const manageTabBtnStyle = (active: boolean): React.CSSProperties => ({
  flexShrink: 0,
  background: active ? '#f1f5f9' : 'none',
  border: active ? '1px solid #e2e8f0' : '1px solid transparent',
  borderRadius: 8,
  padding: '5px 10px',
  fontSize: 11,
  fontWeight: 600,
  color: active ? '#0f172a' : '#94a3b8',
  cursor: 'pointer',
  whiteSpace: 'nowrap',
  marginLeft: 8,
  marginBottom: 2,
  transition: 'background 0.1s, color 0.1s',
});

// Panel styles
const panelStyle: React.CSSProperties = {
  background: '#f8fafc',
  border: '1px solid #e2e8f0',
  borderRadius: 12,
  padding: 14,
  marginTop: 10,
};

const panelCloseBtnStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  cursor: 'pointer',
  fontSize: 14,
  color: '#94a3b8',
  padding: '2px 4px',
  lineHeight: 1,
};

const groupRowStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  padding: '8px 10px',
  background: '#f8fafc',
  borderRadius: 10,
  border: '1px solid #f1f5f9',
};

const panelInputStyle: React.CSSProperties = {
  border: '1px solid #cbd5e1',
  borderRadius: 8,
  padding: '6px 10px',
  fontSize: 13,
  color: '#0f172a',
  background: '#ffffff',
  outline: 'none',
};

const panelActionBtnStyle: React.CSSProperties = {
  border: '1px solid #e2e8f0',
  borderRadius: 8,
  padding: '4px 10px',
  fontSize: 11,
  fontWeight: 600,
  color: '#475569',
  background: '#ffffff',
  cursor: 'pointer',
  whiteSpace: 'nowrap',
};

const tickerRowStyle = (isNarrow: boolean, hasDragHandle: boolean): React.CSSProperties => ({
  display: 'grid',
  // Narrow viewports: stack vertically. The action cluster (move % +
  // Monitor + Remove) gets crowded against the company name/pill block at
  // ≤1180px, especially on phones where the auto-sized right column was
  // wide enough to push into the truncated left content.
  gridTemplateColumns: isNarrow
    ? '1fr'
    : hasDragHandle
      ? 'auto minmax(0, 1fr) auto'
      : 'minmax(0, 1fr) auto',
  alignItems: isNarrow ? 'stretch' : 'center',
  gap: isNarrow ? 8 : 12,
  border: '1px solid #e2e8f0',
  borderRadius: 12,
  padding: '10px 14px',
  background: '#f8fafc',
});

const symbolLinkStyle: React.CSSProperties = {
  fontSize: 14,
  fontWeight: 700,
  color: '#1d4ed8',
  textDecoration: 'none',
};

const tagPillStyle: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 600,
  color: '#475569',
  background: '#e2e8f0',
  borderRadius: 999,
  padding: '1px 7px',
};

const addGroupPillStyle: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 600,
  color: '#94a3b8',
  background: 'none',
  border: '1px dashed #cbd5e1',
  borderRadius: 999,
  padding: '1px 7px',
  cursor: 'pointer',
};

const primaryButtonStyle = (disabled: boolean): React.CSSProperties => ({
  border: 'none',
  borderRadius: 12,
  padding: '11px 14px',
  fontSize: 12,
  fontWeight: 700,
  color: '#ffffff',
  background: disabled ? '#94a3b8' : '#0f172a',
  cursor: disabled ? 'not-allowed' : 'pointer',
  whiteSpace: 'nowrap',
});

const groupDropdownButtonStyle = (disabled: boolean): React.CSSProperties => ({
  border: '1px solid #cbd5e1',
  borderRadius: 10,
  padding: '8px 12px',
  fontSize: 13,
  color: '#0f172a',
  background: '#ffffff',
  cursor: disabled ? 'not-allowed' : 'pointer',
  width: '100%',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  outline: 'none',
});

const groupDropdownListStyle: React.CSSProperties = {
  position: 'absolute',
  top: 'calc(100% + 4px)',
  left: 0,
  right: 0,
  background: '#ffffff',
  border: '1px solid #cbd5e1',
  borderRadius: 10,
  margin: 0,
  padding: 4,
  listStyle: 'none',
  boxShadow: '0 4px 12px rgba(15, 23, 42, 0.08)',
  maxHeight: 240,
  overflowY: 'auto',
  zIndex: 10,
};

const groupDropdownItemStyle = (selected: boolean): React.CSSProperties => ({
  width: '100%',
  textAlign: 'left',
  padding: '8px 10px',
  fontSize: 13,
  border: 'none',
  borderRadius: 6,
  background: selected ? '#f1f5f9' : 'transparent',
  color: '#0f172a',
  cursor: 'pointer',
  outline: 'none',
});

const secondaryButtonStyle = (disabled: boolean): React.CSSProperties => ({
  border: '1px solid #cbd5e1',
  borderRadius: 999,
  padding: '5px 10px',
  fontSize: 11,
  fontWeight: 700,
  color: '#475569',
  background: '#ffffff',
  cursor: disabled ? 'not-allowed' : 'pointer',
});

const monitorToggleStyle = (active: boolean, disabled: boolean): React.CSSProperties => ({
  border: `1px solid ${active ? '#10b981' : '#cbd5e1'}`,
  borderRadius: 999,
  padding: '5px 10px',
  fontSize: 11,
  fontWeight: 700,
  color: active ? '#065f46' : '#475569',
  background: active ? '#ecfdf5' : '#ffffff',
  cursor: disabled ? 'not-allowed' : 'pointer',
  display: 'inline-flex',
  alignItems: 'center',
  gap: 4,
});

export default WatchlistPage;
