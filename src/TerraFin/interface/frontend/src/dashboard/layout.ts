export type DashboardSlot = 'hero' | 'primary' | 'rail';

export interface DashboardWidgetDefinition {
  id: string;
  slot: DashboardSlot;
  order: number;
  mobileOrder: number;
  minHeight?: number;
  fill?: boolean;
}
