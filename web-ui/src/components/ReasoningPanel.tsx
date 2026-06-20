import { useState } from 'react';
import {
  X, Clock, ChevronDown, ChevronRight,
  Brain, Cpu, MessageSquare, ArrowDown,
  CheckCircle2, AlertTriangle, Tag, BookOpen,
  Search, Lightbulb, Database,
} from 'lucide-react';
import { type PipelineStep } from '../api/client';

interface ReasoningPanelProps {
  trace: PipelineStep[];
  onClose: () => void;
}

interface ParsedExtraction {
  has_logic: boolean;
  entities?: string[];
  facts?: unknown[];
  rules?: unknown[];
  query?: unknown;
  expected_answer?: string;
  explanation?: string;
}

// Render a structured term object {pred, args} or rule {head, body} as Prolog
// text. Falls back gracefully for strings/numbers so the UI never crashes when
// the extraction format varies.
function termToString(t: unknown): string {
  if (t == null) return '';
  if (typeof t === 'string') return t;
  if (typeof t === 'number' || typeof t === 'boolean') return String(t);
  if (Array.isArray(t)) return t.map(termToString).join(', ');
  if (typeof t === 'object') {
    const o = t as Record<string, unknown>;
    if ('head' in o) {
      const head = termToString(o.head);
      const body = Array.isArray(o.body) ? (o.body as unknown[]).map(termToString).join(', ') : '';
      return body ? `${head} :- ${body}` : head;
    }
    if ('pred' in o) {
      const args = Array.isArray(o.args) ? (o.args as unknown[]) : [];
      return args.length === 0 ? String(o.pred) : `${o.pred}(${args.map(termToString).join(', ')})`;
    }
    try { return JSON.stringify(o); } catch { return String(o); }
  }
  return String(t);
}

interface ParsedDali2 {
  status: string;
  solution?: string;
  explanation?: string;
  logs?: Array<{ agent: string; message: string; time: number }>;
}

const stepConfig: Record<string, { icon: typeof Brain; color: string; bg: string; border: string }> = {
  extraction:      { icon: Brain,          color: 'text-violet-400', bg: 'bg-violet-500/10', border: 'border-violet-500/30' },
  dali2_solving:   { icon: Cpu,            color: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30' },
  synthesis:       { icon: MessageSquare,  color: 'text-sky-400', bg: 'bg-sky-500/10', border: 'border-sky-500/30' },
  direct_response: { icon: MessageSquare,  color: 'text-gray-400', bg: 'bg-gray-500/10', border: 'border-gray-500/30' },
};

function formatDuration(ms: number | null): string {
  if (!ms) return '';
  return ms > 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

function tryParseJson(content: string): Record<string, unknown> | null {
  try {
    return JSON.parse(content);
  } catch {
    return null;
  }
}

function ExtractionBlock({ data }: { data: ParsedExtraction }) {
  const [showDetails, setShowDetails] = useState(false);

  return (
    <div className="space-y-2">
      {/* Logic detected badge */}
      <div className="flex items-center gap-2">
        {data.has_logic ? (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-500/20 text-amber-300 border border-amber-500/30">
            <Lightbulb className="w-3 h-3" />
            Logic detected
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-gray-500/20 text-gray-400 border border-gray-500/30">
            No logic found
          </span>
        )}
      </div>

      {data.has_logic && (
        <>
          {/* Explanation */}
          {data.explanation && (
            <div className="rounded-lg bg-violet-500/5 border border-violet-500/20 p-3">
              <p className="text-xs text-gray-300 leading-relaxed">{data.explanation}</p>
            </div>
          )}

          {/* Entities */}
          {data.entities && data.entities.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {data.entities.map((e, i) => (
                <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs bg-violet-500/15 text-violet-300 border border-violet-500/20">
                  <Tag className="w-2.5 h-2.5" />
                  {e}
                </span>
              ))}
            </div>
          )}

          {/* Expandable facts/rules/query */}
          <button
            onClick={() => setShowDetails(!showDetails)}
            className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300 transition-colors"
          >
            {showDetails ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            Prolog details
          </button>

          {showDetails && (
            <div className="space-y-2 pl-2 border-l-2 border-violet-500/20">
              {data.facts && data.facts.length > 0 && (
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-gray-600 mb-1">Facts</p>
                  {data.facts.map((f, i) => (
                    <code key={i} className="block text-xs text-violet-300/80 font-mono break-all">{termToString(f)}.</code>
                  ))}
                </div>
              )}
              {data.rules && data.rules.length > 0 && (
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-gray-600 mb-1">Rules</p>
                  {data.rules.map((r, i) => (
                    <code key={i} className="block text-xs text-violet-300/80 font-mono break-all">{termToString(r)}.</code>
                  ))}
                </div>
              )}
              {data.query != null && (
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-gray-600 mb-1">Query</p>
                  <code className="text-xs text-amber-300 font-mono break-all">?- {termToString(data.query)}.</code>
                </div>
              )}
              {data.expected_answer && (
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-gray-600 mb-1">Expected</p>
                  <code className="text-xs text-gray-400 font-mono">{data.expected_answer}</code>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Dali2Block({ data }: { data: ParsedDali2 }) {
  const [showLogs, setShowLogs] = useState(false);

  const statusConfig: Record<string, { label: string; icon: typeof CheckCircle2; cls: string }> = {
    solved:          { label: 'Solved',           icon: CheckCircle2,  cls: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' },
    used_extraction: { label: 'Extraction used',  icon: AlertTriangle, cls: 'bg-amber-500/20 text-amber-300 border-amber-500/30' },
    fallback:        { label: 'Fallback',         icon: AlertTriangle, cls: 'bg-red-500/20 text-red-300 border-red-500/30' },
  };

  const st = statusConfig[data.status] || statusConfig.fallback;
  const StatusIcon = st.icon;

  return (
    <div className="space-y-2">
      {/* Status badge */}
      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border ${st.cls}`}>
        <StatusIcon className="w-3 h-3" />
        {st.label}
      </span>

      {/* Explanation */}
      {data.explanation && (
        <div className="rounded-lg bg-emerald-500/5 border border-emerald-500/20 p-3">
          <p className="text-xs text-gray-300 leading-relaxed">{data.explanation}</p>
        </div>
      )}

      {/* Solution */}
      {data.solution && (
        <div>
          <p className="text-[10px] uppercase tracking-wider text-gray-600 mb-1">Solution</p>
          <code className="text-xs text-emerald-300 font-mono">{data.solution}</code>
        </div>
      )}

      {/* Logs */}
      {data.logs && data.logs.length > 0 && (
        <>
          <button
            onClick={() => setShowLogs(!showLogs)}
            className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300 transition-colors"
          >
            {showLogs ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            Agent logs ({data.logs.length})
          </button>

          {showLogs && (
            <div className="space-y-0.5 max-h-48 overflow-y-auto pl-2 border-l-2 border-emerald-500/20">
              {data.logs.map((log, i) => (
                <div key={i} className="flex gap-2 text-[11px]">
                  <span className="text-emerald-500/60 font-mono flex-shrink-0">{log.agent}</span>
                  <span className="text-gray-500 break-all">{log.message}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function SynthesisBlock({ content }: { content: string }) {
  return (
    <div className="rounded-lg bg-sky-500/5 border border-sky-500/20 p-3">
      <p className="text-xs text-gray-300 leading-relaxed">{content}</p>
    </div>
  );
}

function StepBlock({ step, index, total }: { step: PipelineStep; index: number; total: number }) {
  const config = stepConfig[step.step] || stepConfig.direct_response;
  const Icon = config.icon;
  const parsed = tryParseJson(step.content);

  return (
    <div className="flex flex-col items-center">
      {/* Block */}
      <div className={`w-full rounded-xl border ${config.border} ${config.bg} overflow-hidden transition-all`}>
        {/* Block header */}
        <div className={`flex items-center justify-between px-4 py-2.5 border-b ${config.border}`}>
          <div className="flex items-center gap-2">
            <div className={`w-7 h-7 rounded-lg ${config.bg} border ${config.border} flex items-center justify-center`}>
              <Icon className={`w-3.5 h-3.5 ${config.color}`} />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-gray-200">{step.title}</h3>
              <p className="text-[10px] text-gray-500 uppercase tracking-wider">Step {index + 1} of {total}</p>
            </div>
          </div>
          {step.duration_ms != null && step.duration_ms > 0 && (
            <span className="flex items-center gap-1 text-xs text-gray-500 bg-gray-800/50 px-2 py-1 rounded-md">
              <Clock className="w-3 h-3" />
              {formatDuration(step.duration_ms)}
            </span>
          )}
        </div>

        {/* Block content */}
        <div className="px-4 py-3">
          {step.step === 'extraction' && parsed ? (
            <ExtractionBlock data={parsed as unknown as ParsedExtraction} />
          ) : step.step === 'dali2_solving' && parsed ? (
            <Dali2Block data={parsed as unknown as ParsedDali2} />
          ) : step.step === 'synthesis' || step.step === 'direct_response' ? (
            <SynthesisBlock content={step.content} />
          ) : (
            <pre className="text-xs text-gray-400 whitespace-pre-wrap break-words">{step.content}</pre>
          )}
        </div>
      </div>

      {/* Arrow connector */}
      {index < total - 1 && (
        <div className="flex flex-col items-center py-1">
          <div className="w-px h-4 bg-gray-700" />
          <ArrowDown className="w-4 h-4 text-gray-600" />
          <div className="w-px h-1 bg-gray-700" />
        </div>
      )}
    </div>
  );
}

export function ReasoningPanel({ trace, onClose }: ReasoningPanelProps) {
  const totalDuration = trace.reduce((sum, s) => sum + (s.duration_ms || 0), 0);

  return (
    <aside className="w-[420px] border-l border-gray-800 bg-gray-900 flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-gray-800">
        <div>
          <h2 className="text-sm font-semibold text-gray-200 flex items-center gap-2">
            <Search className="w-4 h-4 text-primary-400" />
            Reasoning Trace
          </h2>
          {totalDuration > 0 && (
            <p className="text-xs text-gray-500 mt-0.5">
              Total: {formatDuration(totalDuration)} &middot; {trace.length} steps
            </p>
          )}
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded-lg hover:bg-gray-800 text-gray-400 hover:text-gray-200 transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Flow diagram */}
      <div className="flex-1 overflow-y-auto p-4">
        {/* Start node */}
        <div className="flex flex-col items-center mb-1">
          <div className="w-full flex items-center justify-center gap-2 py-2 px-4 rounded-lg bg-gray-800 border border-gray-700">
            <Database className="w-3.5 h-3.5 text-gray-400" />
            <span className="text-xs font-medium text-gray-400">User Prompt</span>
          </div>
          <div className="flex flex-col items-center py-1">
            <div className="w-px h-4 bg-gray-700" />
            <ArrowDown className="w-4 h-4 text-gray-600" />
            <div className="w-px h-1 bg-gray-700" />
          </div>
        </div>

        {/* Pipeline steps */}
        {trace.map((step, i) => (
          <StepBlock key={i} step={step} index={i} total={trace.length} />
        ))}

        {/* End node */}
        <div className="flex flex-col items-center mt-1">
          <div className="flex flex-col items-center py-1">
            <div className="w-px h-2 bg-gray-700" />
            <ArrowDown className="w-4 h-4 text-gray-600" />
          </div>
          <div className="w-full flex items-center justify-center gap-2 py-2 px-4 rounded-lg bg-primary-600/10 border border-primary-500/30">
            <BookOpen className="w-3.5 h-3.5 text-primary-400" />
            <span className="text-xs font-medium text-primary-400">Final Answer</span>
          </div>
        </div>
      </div>
    </aside>
  );
}
