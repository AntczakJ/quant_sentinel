/**
 * drawings/types.ts — Core type system for manual drawing tools.
 */

export const DRAWING_TOOLS = [
  'cursor',       // default pointer (no drawing)
  'trendline',    // line between two points
  'ray',          // line extending right from two points
  'extendedline', // line extending both directions
  'hline',        // horizontal line at a price
  'vline',        // vertical line at a time
  'channel',      // parallel channel (3 clicks)
  'fib',          // fibonacci retracement (2 points)
  'rect',         // rectangle (2 corners)
  'path',         // freehand brush
  'text',         // text annotation
  'measure',      // price range / measure tool
  'longposition', // long position (entry + TP + SL)
  'shortposition',// short position (entry + TP + SL)
] as const;

export type DrawingTool = (typeof DRAWING_TOOLS)[number];

export interface DrawingPoint {
  time: number;   // UTC timestamp
  price: number;
}

export interface FibLevel {
  level: number;     // 0 … 1
  visible: boolean;
  color: string;
}

export interface DrawingStyle {
  color: string;
  lineWidth: number;
  lineStyle: 'solid' | 'dashed' | 'dotted';
  fillColor: string;
  fontSize: number;
  text: string;
  fibLevels?: FibLevel[];
}

export const DEFAULT_FIB_LEVELS: FibLevel[] = [
  { level: 0,     visible: true, color: 'rgba(239,68,68,0.6)' },
  { level: 0.236, visible: true, color: 'rgba(249,115,22,0.6)' },
  { level: 0.382, visible: true, color: 'rgba(234,179,8,0.6)' },
  { level: 0.5,   visible: true, color: 'rgba(156,163,175,0.6)' },
  { level: 0.618, visible: true, color: 'rgba(34,197,94,0.6)' },
  { level: 0.786, visible: true, color: 'rgba(59,130,246,0.6)' },
  { level: 1,     visible: true, color: 'rgba(139,92,246,0.6)' },
];

export interface Drawing {
  id: string;
  tool: DrawingTool;
  points: DrawingPoint[];
  style: DrawingStyle;
  visible: boolean;
  locked?: boolean;
}

/** How many clicks each tool requires (0 = freehand / variable) */
export function requiredPoints(tool: DrawingTool): number {
  switch (tool) {
    case 'hline':        return 1;
    case 'vline':        return 1;
    case 'text':         return 1;
    case 'trendline':    return 2;
    case 'ray':          return 2;
    case 'extendedline': return 2;
    case 'fib':          return 2;
    case 'rect':         return 2;
    case 'measure':      return 2;
    case 'longposition': return 2;
    case 'shortposition':return 2;
    case 'channel':      return 3;
    case 'path':         return 0; // variable (mousedown → mouseup)
    default:             return 0;
  }
}

export const DEFAULT_STYLE: DrawingStyle = {
  color: '#3b82f6',
  lineWidth: 2,
  lineStyle: 'solid',
  fillColor: 'rgba(59,130,246,0.12)',
  fontSize: 12,
  text: '',
};

/** Generate unique id */
export function uid(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

