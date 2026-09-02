import {
  Bot,
  CheckCircle2,
  Database,
  GitBranch,
  Server,
  ShieldAlert,
  Target,
  Workflow,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';

const features = [
  { label: 'Fast trend', value: '−0.64%', width: '38%', tone: 'bg-rose-300' },
  { label: 'Slow trend', value: '−1.32%', width: '62%', tone: 'bg-rose-300' },
  { label: 'Relative volume', value: '0.96×', width: '72%', tone: 'bg-cyan-300' },
  { label: 'Realized vol', value: '0.45%', width: '28%', tone: 'bg-amber-300' },
];

const timeline = [
  { icon: Database, title: 'Market observed', copy: '98 completed daily bars · IEX spot $760.98', time: '15:39:18' },
  { icon: Bot, title: 'Thesis proposed', copy: 'Bear regime with aligned features · confidence 0.95', time: '15:39:18' },
  { icon: ShieldAlert, title: 'Critic challenged', copy: 'Approved with counter-evidence retained', time: '15:39:18' },
  { icon: GitBranch, title: 'Spread selected', copy: '765/755 put vertical · delta method', time: '15:39:19' },
  { icon: Target, title: 'Risk decided', copy: 'Candidate blocked · no broker write', time: '15:39:19' },
];

export function DecisionDetails() {
  return (
    <>
      <section className="mt-4 grid gap-4 lg:grid-cols-[1.05fr_.95fr]">
        <Card className="border-white/8 bg-card/75">
          <CardHeader className="border-b border-white/8">
            <CardTitle>Spread anatomy</CardTitle>
            <CardDescription>Conservative executable prices, before fees and slippage.</CardDescription>
            <CardAction>
              <Badge variant="outline" className="border-cyan-200/15 text-cyan-100">Delta selected</Badge>
            </CardAction>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 sm:grid-cols-[1fr_auto_1fr] sm:items-stretch">
              <div className="rounded-xl border border-emerald-300/15 bg-emerald-300/[0.045] p-4">
                <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-emerald-200">Buy to open</p>
                <p className="mt-3 text-2xl font-semibold">765 Put</p>
                <p className="mt-1 font-mono text-xs text-muted-foreground">SPY260915P00765000</p>
                <div className="mt-4 flex justify-between text-xs">
                  <span className="text-muted-foreground">Ask</span>
                  <span className="font-mono text-white">$7.74</span>
                </div>
              </div>
              <div className="flex items-center justify-center py-1 sm:flex-col sm:py-0">
                <span className="h-px flex-1 bg-white/10 sm:h-full sm:w-px" />
                <span className="rounded-full border border-white/10 bg-[#101d2b] px-3 py-1.5 font-mono text-[10px] text-slate-300">$10 WIDTH</span>
                <span className="h-px flex-1 bg-white/10 sm:h-full sm:w-px" />
              </div>
              <div className="rounded-xl border border-rose-300/15 bg-rose-300/[0.045] p-4">
                <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-rose-200">Sell to open</p>
                <p className="mt-3 text-2xl font-semibold">755 Put</p>
                <p className="mt-1 font-mono text-xs text-muted-foreground">SPY260915P00755000</p>
                <div className="mt-4 flex justify-between text-xs">
                  <span className="text-muted-foreground">Bid</span>
                  <span className="font-mono text-white">$3.88</span>
                </div>
              </div>
            </div>
            <dl className="mt-4 grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-white/8 bg-white/8 sm:grid-cols-4">
              {[
                ['Net debit', '$3.86'],
                ['Breakeven', '$761.14'],
                ['Expiration', '15 Sep'],
                ['DTE', '14 days'],
              ].map(([label, value]) => (
                <div key={label} className="bg-[#101d2b] p-3.5">
                  <dt className="text-[10px] uppercase tracking-[0.13em] text-muted-foreground">{label}</dt>
                  <dd className="mt-1.5 font-mono text-sm text-white">{value}</dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>

        <Card className="border-white/8 bg-card/75">
          <CardHeader className="border-b border-white/8">
            <CardTitle>Signal snapshot</CardTitle>
            <CardDescription>Feature set 2026.08.24.v1 · 98 source bars</CardDescription>
            <CardAction><Badge className="bg-rose-300/10 text-rose-100">Bear regime</Badge></CardAction>
          </CardHeader>
          <CardContent className="space-y-5">
            {features.map((feature) => (
              <div key={feature.label}>
                <div className="mb-2 flex items-center justify-between gap-4 text-xs">
                  <span className="text-muted-foreground">{feature.label}</span>
                  <span className="font-mono text-white">{feature.value}</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-white/7">
                  <div className={`h-full rounded-full ${feature.tone}`} style={{ width: feature.width }} />
                </div>
              </div>
            ))}
            <div className="rounded-xl border border-white/8 bg-black/10 p-4">
              <p className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Counter-evidence retained</p>
              <p className="mt-2 text-sm leading-relaxed text-slate-300">
                Realized volatility 0.45% · ATR $5.23 · relative strength neutral. The model cannot delete facts that weaken its own thesis.
              </p>
            </div>
          </CardContent>
        </Card>
      </section>

      <section className="mt-4 grid gap-4 lg:grid-cols-[1.15fr_.85fr]">
        <Card className="border-white/8 bg-card/75">
          <CardHeader className="border-b border-white/8">
            <CardTitle className="flex items-center gap-2"><Workflow className="size-4 text-cyan-200" /> Decision trace</CardTitle>
            <CardDescription>One decision, ordered evidence, no hidden execution step.</CardDescription>
          </CardHeader>
          <CardContent>
            <ol>
              {timeline.map((event, index) => (
                <li key={event.title} className="relative grid grid-cols-[34px_1fr_auto] gap-3 pb-5 last:pb-0">
                  {index < timeline.length - 1 && <span className="absolute left-4 top-8 h-[calc(100%-20px)] w-px bg-white/8" />}
                  <span className="relative z-10 grid size-8 place-items-center rounded-lg border border-cyan-200/10 bg-cyan-200/[0.055] text-cyan-100"><event.icon className="size-3.5" /></span>
                  <div>
                    <p className="text-sm font-medium text-white/90">{event.title}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">{event.copy}</p>
                  </div>
                  <time className="pt-0.5 font-mono text-[10px] text-muted-foreground">{event.time}</time>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>

        <Card className="border-white/8 bg-card/75">
          <CardHeader className="border-b border-white/8">
            <CardTitle className="flex items-center gap-2"><Server className="size-4 text-emerald-200" /> System health</CardTitle>
            <CardDescription>Evidence-backed status at capture time.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {[
              ['Alpaca paper API', 'Healthy', 'emerald'],
              ['IEX stock feed', 'Healthy', 'emerald'],
              ['Indicative option feed', '323 snapshots', 'emerald'],
              ['Alpaca MCP profile', '32 read tools', 'emerald'],
              ['Broker reconciliation', 'Intentionally off', 'amber'],
              ['Order gateway', 'Not installed', 'rose'],
            ].map(([name, state, tone]) => (
              <div key={name} className="flex items-center justify-between gap-4 rounded-lg border border-white/7 bg-black/10 px-3.5 py-3">
                <span className="text-sm text-slate-300">{name}</span>
                <span className={`flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.1em] ${tone === 'emerald' ? 'text-emerald-200' : tone === 'amber' ? 'text-amber-200' : 'text-rose-200'}`}>
                  <span className={`size-1.5 rounded-full ${tone === 'emerald' ? 'bg-emerald-300' : tone === 'amber' ? 'bg-amber-300' : 'bg-rose-300'}`} />
                  {state}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      </section>

      <footer className="mt-8 flex flex-col justify-between gap-3 border-t border-white/8 py-5 text-xs text-muted-foreground sm:flex-row sm:items-center">
        <p>Paper trading only · Captured market evidence · Not financial advice</p>
        <p className="font-mono">PHASE 6 · OBSERVABILITY</p>
      </footer>
    </>
  );
}
