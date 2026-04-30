import React, { useEffect, useMemo, useRef, useState } from 'react';
import DashboardHeader from '../dashboard/components/DashboardHeader';
import InsightCard from '../dashboard/components/InsightCard';
import { BREAKPOINTS } from '../shared/responsive';
import TickerSearchInput from '../shared/TickerSearchInput';
import { WatchlistItem, useWatchlist } from './useWatchlist';

const NARROW_LAYOUT_BREAKPOINT = BREAKPOINTS.TABLET_MAX + 157; // 1180

// ─── Helpers ─────────────────────────────────────────────────────────────────

function nextDefaultGroupName(existingNames: string[]): string {
  let n = 1;
  while (existingNames.includes(`base group ${n}`)) n++;
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
  isPending: boolean;
}

function buildDisplayGroups(
  items: WatchlistItem[],
  groupTags: string[],
  pendingGroups: string[],
): DisplayGroup[] {
  const result: DisplayGroup[] = groupTags.map((tag) => ({
    name: tag,
    items: items.filter((item) => item.tags.includes(tag)),
    isSynthetic: false,
    isPending: pendingGroups.includes(tag),
  }));

  const untagged = items.filter((item) => item.tags.length === 0);
  if (untagged.length > 0) {
    const syntheticName = nextDefaultGroupName(groupTags);
    result.unshift({ name: syntheticName, items: untagged, isSynthetic: true, isPending: false });
  }

  if (result.length === 0) {
    result.push({ name: 'Base Group 1', items: [], isSynthetic: true, isPending: true });
  }

  return result;
}

// ─── Group management panel ───────────────────────────────────────────────────

interface GroupManagePanelProps {
  displayGroups: DisplayGroup[];
  pendingGroups: string[];
  busy: boolean;
  onRename: (group: DisplayGroup, newName: string) => Promise<void>;
  onDelete: (group: DisplayGroup) => Promise<void>;
  onAddGroup: (name: string) => void;
  onClose: () => void;
}

const GroupManagePanel: React.FC<GroupManagePanelProps> = ({
  displayGroups,
  pendingGroups,
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

  const handleAddGroup = () => {
    const name = newGroupInput.trim();
    setNewGroupInput('');
    if (!name) return;
    onAddGroup(name);
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
          const isPending = pendingGroups.includes(group.name);

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
                  {isPending && (
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
          onKeyDown={(e) => { if (e.key === 'Enter') { handleAddGroup(); } }}
          placeholder="New group name…"
          style={{ ...panelInputStyle, flex: 1 }}
        />
        <button
          type="button"
          onClick={handleAddGroup}
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
  const [pendingGroups, setPendingGroups] = useState<string[]>([]);
  const [isManagePanelOpen, setIsManagePanelOpen] = useState(false);
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
    deleteGroup,
    promoteGroup,
    backendConfigured,
  } = useWatchlist();

  const groupTags = useMemo(() => {
    const realTags = groups.map((g) => g.tag);
    const newPending = pendingGroups.filter((p) => !realTags.includes(p));
    return [...realTags, ...newPending];
  }, [groups, pendingGroups]);

  // Clear pending groups that materialized as real groups
  useEffect(() => {
    const realTags = groups.map((g) => g.tag);
    setPendingGroups((prev) => prev.filter((p) => !realTags.includes(p)));
  }, [groups]);

  const displayGroups = useMemo(
    () => buildDisplayGroups(items, groupTags, pendingGroups),
    [items, groupTags, pendingGroups],
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

  const visibleItems = activeDisplayGroup?.items ?? [];

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
    } catch {
      // handled in hook
    }
  };

  const handleRenameGroup = async (group: DisplayGroup, newName: string) => {
    const old = group.name;
    const normalized = newName.trim();
    if (!normalized) return;
    if (pendingGroups.includes(old)) {
      setPendingGroups((prev) => prev.map((p) => (p === old ? normalized : p)));
      if (activeGroup === old) setActiveGroup(normalized);
      return;
    }
    if (group.isSynthetic) {
      if (group.items.length === 0) {
        // Empty placeholder — just register as a pending named group
        setPendingGroups((prev) => (prev.includes(normalized) ? prev : [...prev, normalized]));
        setActiveGroup(normalized);
      } else {
        // Untagged items exist — add the new tag to all of them
        await promoteGroup(group.items, normalized, items);
        setActiveGroup(normalized);
      }
      return;
    }
    await renameGroup(old, normalized);
    setActiveGroup(normalized);
  };

  const handleDeleteGroup = async (group: DisplayGroup) => {
    if (pendingGroups.includes(group.name)) {
      setPendingGroups((prev) => prev.filter((p) => p !== group.name));
      const remaining = displayGroups.filter((g) => g.name !== group.name);
      setActiveGroup(remaining[0]?.name ?? null);
      return;
    }
    if (group.isSynthetic) {
      // No tag to strip — remove these untagged items from the watchlist
      for (const item of group.items) {
        await removeSymbol(item.symbol); // eslint-disable-line
      }
    } else {
      await deleteGroup(group.name, items);
    }
    const remaining = displayGroups.filter((g) => g.name !== group.name);
    setActiveGroup(remaining[0]?.name ?? null);
  };

  const handleAddNewGroup = (name: string) => {
    const trimmed = name.trim().toLowerCase();
    if (!trimmed) return;
    if (!groupTags.includes(trimmed)) {
      setPendingGroups((prev) => [...prev, trimmed]);
    }
    setActiveGroup(trimmed);
    setIsManagePanelOpen(false);
  };

  const subtitle = useMemo(() => {
    if (items.length === 0) return 'Build a TerraFin watchlist and keep your core tickers in one place.';
    const total = items.length;
    const gc = displayGroups.length;
    return `${total} ticker${total !== 1 ? 's' : ''} across ${gc} group${gc !== 1 ? 's' : ''}.`;
  }, [items.length, displayGroups.length]);

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
              <div style={{ fontSize: 12, color: '#b91c1c' }}>
                {error}
                {error.toLowerCase().includes('already') && (
                  <span style={{ color: '#475569', display: 'block', marginTop: 2 }}>
                    To add to another group, use the "+ group" button on the ticker row.
                  </span>
                )}
              </div>
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
              <div style={tabBarWrapperStyle}>
                <div style={tabBarStyle}>
                  {displayGroups.map((group) => {
                    const isActive = group.name === activeGroup;
                    return (
                      <button
                        key={group.name}
                        type="button"
                        onClick={() => setActiveGroup(group.name)}
                        style={tabStyle(isActive)}
                      >
                        {group.name}
                        <span style={{ marginLeft: 5, fontSize: 11, opacity: 0.65 }}>
                          {group.items.length}
                        </span>
                      </button>
                    );
                  })}
                </div>
                {/* Manage button */}
                {backendConfigured && (
                  <button
                    type="button"
                    onClick={() => setIsManagePanelOpen((v) => !v)}
                    style={manageTabBtnStyle(isManagePanelOpen)}
                    title="Manage groups"
                  >⚙ Manage</button>
                )}
              </div>

              {/* Group management panel */}
              {isManagePanelOpen && (
                <GroupManagePanel
                  displayGroups={displayGroups}
                  pendingGroups={pendingGroups}
                  busy={busy}
                  onRename={handleRenameGroup}
                  onDelete={handleDeleteGroup}
                  onAddGroup={handleAddNewGroup}
                  onClose={() => setIsManagePanelOpen(false)}
                />
              )}

              {/* Ticker list */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 12 }}>
                {visibleItems.length === 0 ? (
                  <div style={{ fontSize: 13, color: '#94a3b8', padding: '12px 0' }}>
                    No tickers in this group yet. Add one using the form on the left.
                  </div>
                ) : (
                  visibleItems.map((item) => {
                    const otherGroupTags = item.tags.filter((t) => t !== activeGroup);
                    const availableGroups = groupTags.filter((g) => !item.tags.includes(g));
                    return (
                      <div key={item.symbol} style={tickerRowStyle}>
                        {/* Symbol + name + cross-group pills */}
                        <div style={{ minWidth: 0 }}>
                          <a href={`/stock/${item.symbol}`} style={symbolLinkStyle}>{item.symbol}</a>
                          {item.name && item.name !== item.symbol ? (
                            <div style={{ fontSize: 12, color: '#64748b', marginTop: 1 }}>{item.name}</div>
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
                                      onClick={() => { void setTags(item.symbol, [tag], 'remove'); }}
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
                                      if (e.target.value) { void setTags(item.symbol, [e.target.value], 'add'); }
                                      setAssigningTickerFor(null);
                                    }}
                                    onBlur={() => setAssigningTickerFor(null)}
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
                                    onClick={() => setAssigningTickerFor(item.symbol)}
                                    style={addGroupPillStyle}
                                  >+ group</button>
                                )
                              )}
                            </div>
                          )}
                        </div>

                        {/* Move % + remove */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
                          <span style={{ fontSize: 13, fontWeight: 700, color: moveColor(item.move) }}>
                            {item.move}
                          </span>
                          {backendConfigured ? (
                            <button
                              type="button"
                              onClick={() => { void removeSymbol(item.symbol); }}
                              disabled={busy}
                              style={secondaryButtonStyle(busy)}
                            >
                              Remove
                            </button>
                          ) : null}
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
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

const tickerRowStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'minmax(0, 1fr) auto',
  alignItems: 'center',
  gap: 12,
  border: '1px solid #e2e8f0',
  borderRadius: 12,
  padding: '10px 14px',
  background: '#f8fafc',
};

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

export default WatchlistPage;
