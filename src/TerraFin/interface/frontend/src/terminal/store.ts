import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

/**
 * Global terminal state — small on purpose. Anything that wants to react
 * to "current ticker" / "active layout preset" / "is the palette open" /
 * "is the agent thinking" subscribes via a selector so unrelated state
 * changes (like the 1-second status-bar clock) don't re-render widgets.
 */

export type LayoutPreset = 'trader' | 'macro' | 'research';
export type AgentActivity = 'idle' | 'thinking' | 'streaming' | 'error';
export type ThemeMode = 'dark' | 'light';

interface TerminalState {
  activeTicker: string | null;
  layoutPreset: LayoutPreset;
  agentActivity: AgentActivity;
  theme: ThemeMode;
  lastDataAt: number | null;

  setActiveTicker: (t: string | null) => void;
  setLayoutPreset: (p: LayoutPreset) => void;
  setAgentActivity: (a: AgentActivity) => void;
  setTheme: (t: ThemeMode) => void;
  toggleTheme: () => void;
  markDataFresh: () => void;
}

export const useTerminalStore = create<TerminalState>()(
  persist(
    (set) => ({
      activeTicker: null,
      layoutPreset: 'trader',
      agentActivity: 'idle',
      theme: 'dark',
      lastDataAt: null,

      setActiveTicker: (t) => set({ activeTicker: t }),
      setLayoutPreset: (p) => set({ layoutPreset: p }),
      setAgentActivity: (a) => set({ agentActivity: a }),
      setTheme: (t) => set({ theme: t }),
      toggleTheme: () => set((s) => ({ theme: s.theme === 'dark' ? 'light' : 'dark' })),
      markDataFresh: () => set({ lastDataAt: Date.now() }),
    }),
    {
      name: 'terrafin.terminal',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ layoutPreset: state.layoutPreset, theme: state.theme }),
    },
  ),
);
