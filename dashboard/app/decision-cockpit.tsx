import {
  Activity,
  ArrowDownRight,
  Ban,
  Bot,
  CheckCircle2,
  Clock3,
  LockKeyhole,
  ShieldCheck,
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
import { DecisionDetails } from './decision-details';

const evidence = [
  'regime = bear',
  'fast trend = −0.64%',
  'slow trend = −1.32%',
  'relative volume = 0.96×',
];

const gates = [
  'Execution is disabled',
  'Dry-run mode cannot submit orders',
  'Local and broker state are not reconciled',
  'Entry is blocked near market close',
];

const funnel = [
  ['323', 'normalized candidates'],
  ['316', 'liquidity eligible'],
  ['11,534', 'valid pairs compared'],
  ['1', 'defined-risk spread'],
  ['0', 'orders submitted'],
];

export function DecisionCockpit() {
  return (
    <main className="min-h-screen bg-background text-foreground">
      <header className="border-b border-white/8 bg-[#08111d]/92 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1500px] items-center justify-between gap-5 px-5 py-4 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="grid size-10 place-items-center rounded-xl border border-emerald-300/20 bg-emerald-300/10 text-emerald-300">
              <Activity className="size-5" />
            </div>
            <div>
              <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-emerald-300/80">
                Alpaca paper intelligence
              </p>
              <h1 className="text-lg font-semibold tracking-tight">ConvictionSpread</h1>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge className="border border-amber-300/20 bg-amber-300/10 text-amber-200">
              <Clock3 data-icon="inline-start" /> Market closed
            </Badge>
            <Badge className="hidden border border-emerald-300/20 bg-emerald-300/10 text-emerald-200 sm:inline-flex">
              <LockKeyhole data-icon="inline-start" /> Read only
            </Badge>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-[1500px] px-5 py-6 lg:px-8 lg:py-8">
        <section className="mb-5 flex flex-col justify-between gap-4 md:flex-row md:items-end">
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
              <span>Decision capture</span>
              <span className="text-white/20">/</span>
              <span className="font-mono">shadow-4d56…228f</span>
            </div>
            <h2 className="max-w-3xl text-3xl font-semibold leading-tight tracking-[-0.035em] md:text-4xl">
              A bearish thesis survived the critic.
              <span className="text-muted-foreground"> The order did not.</span>
            </h2>
          </div>
          <div className="shrink-0 text-left md:text-right">
            <p className="font-mono text-xs text-muted-foreground">CAPTURED 01 SEP 2026 · 15:39 ET</p>
            <p className="mt-1 text-sm text-emerald-200">Paper shadow · Alpaca Indicative</p>
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(320px,.72fr)]">
          <Card className="decision-card min-h-[390px] border-0 py-0 ring-0">
            <CardHeader className="border-b border-white/8 px-6 py-5 md:px-7">
              <div className="flex flex-wrap items-center gap-3">
                <Badge className="h-7 bg-rose-400/12 px-3 text-rose-200">
                  <ArrowDownRight data-icon="inline-start" /> Bearish
                </Badge>
                <span className="font-mono text-xs text-muted-foreground">30 MIN VALIDITY</span>
              </div>
              <CardAction>
                <div className="text-right">
                  <p className="font-mono text-4xl font-semibold tracking-[-0.06em] text-white">0.95</p>
                  <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">confidence</p>
                </div>
              </CardAction>
            </CardHeader>
            <CardContent className="grid flex-1 gap-6 px-6 py-6 md:grid-cols-[1fr_240px] md:px-7">
              <div>
                <div className="mb-5 flex items-start gap-3">
                  <div className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-cyan-300/10 text-cyan-200">
                    <Bot className="size-4" />
                  </div>
                  <div>
                    <p className="text-xs font-medium uppercase tracking-[0.14em] text-cyan-200/80">Agent thesis</p>
                    <p className="mt-2 max-w-2xl text-lg leading-relaxed text-white/92">
                      SPY is in a bear regime with fast and slow momentum aligned. Express the view with a defined-risk put spread, not an uncapped directional position.
                    </p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  {evidence.map((item) => (
                    <span key={item} className="rounded-md border border-white/8 bg-white/[0.035] px-2.5 py-1.5 font-mono text-[11px] text-slate-300">
                      {item}
                    </span>
                  ))}
                </div>
              </div>
              <div className="rounded-xl border border-white/8 bg-[#091421]/80 p-4">
                <div className="flex items-center gap-2 text-emerald-200">
                  <CheckCircle2 className="size-4" />
                  <p className="text-xs font-semibold uppercase tracking-[0.13em]">Critic approved</p>
                </div>
                <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                  No deterministic contradiction exceeded the rejection threshold.
                </p>
                <div className="mt-5 border-t border-white/8 pt-4">
                  <p className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground">Invalidation</p>
                  <p className="mt-1.5 font-mono text-sm text-white">SPY closes above $766.21</p>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="border-white/8 bg-card/80">
            <CardHeader className="border-b border-white/8">
              <CardTitle>Decision funnel</CardTitle>
              <CardDescription>Every narrowing step is deterministic.</CardDescription>
              <CardAction>
                <Badge variant="outline" className="border-white/10 text-slate-300">SPY</Badge>
              </CardAction>
            </CardHeader>
            <CardContent className="pt-1">
              <ol className="relative space-y-0">
                {funnel.map(([value, label], index) => (
                  <li key={label} className="group relative grid grid-cols-[46px_1fr] gap-3 pb-4 last:pb-0">
                    {index < funnel.length - 1 && <span className="absolute left-[22px] top-8 h-[calc(100%-18px)] w-px bg-white/8" />}
                    <span className={`relative z-10 grid size-11 place-items-center rounded-lg border font-mono text-xs ${index === funnel.length - 1 ? 'border-rose-300/20 bg-rose-300/10 text-rose-200' : 'border-cyan-300/15 bg-cyan-300/[0.07] text-cyan-100'}`}>
                      {value}
                    </span>
                    <div className="pt-1">
                      <p className="text-sm font-medium capitalize text-white/90">{label}</p>
                      <p className="mt-0.5 text-xs text-muted-foreground">{index === funnel.length - 1 ? 'Risk boundary held' : 'Passed to next gate'}</p>
                    </div>
                  </li>
                ))}
              </ol>
            </CardContent>
          </Card>
        </section>

        <section className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {[
            ['SPY', '$760.98', 'reference price'],
            ['765 / 755', 'PUT', 'selected vertical'],
            ['$386', 'MAX LOSS', 'one contract'],
            ['$614', 'MAX PROFIT', 'before costs'],
          ].map(([label, value, detail]) => (
            <Card key={label} size="sm" className="border-white/8 bg-card/70">
              <CardContent className="flex items-end justify-between gap-4">
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">{label}</p>
                  <p className="mt-2 text-2xl font-semibold tracking-tight text-white">{value}</p>
                </div>
                <p className="pb-0.5 text-right text-xs text-muted-foreground">{detail}</p>
              </CardContent>
            </Card>
          ))}
        </section>

        <section className="mt-4 grid gap-4 lg:grid-cols-[1fr_1.05fr]">
          <Card className="border-rose-300/10 bg-rose-300/[0.035]">
            <CardHeader className="border-b border-white/8">
              <CardTitle className="flex items-center gap-2 text-rose-100">
                <Ban className="size-4" /> Submission blocked
              </CardTitle>
              <CardDescription>Maximum allowed quantity: 1 · Approved quantity: 0</CardDescription>
            </CardHeader>
            <CardContent>
              <ul className="grid gap-2 sm:grid-cols-2">
                {gates.map((gate) => (
                  <li key={gate} className="flex gap-2 rounded-lg border border-white/7 bg-black/10 p-3 text-sm text-slate-300">
                    <span className="mt-1 size-1.5 shrink-0 rounded-full bg-rose-300" />
                    {gate}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>

          <Card className="border-emerald-300/10 bg-emerald-300/[0.035]">
            <CardHeader className="border-b border-white/8">
              <CardTitle className="flex items-center gap-2 text-emerald-100">
                <ShieldCheck className="size-4" /> Safety proof
              </CardTitle>
              <CardDescription>The dashboard reports broker truth; it never implies a fill.</CardDescription>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {['Paper only', 'GET-only data', 'No order payload', 'No account ID'].map((item) => (
                <div key={item} className="rounded-lg border border-emerald-200/10 bg-black/10 px-3 py-3">
                  <CheckCircle2 className="mb-2 size-4 text-emerald-300" />
                  <p className="text-xs font-medium text-emerald-50">{item}</p>
                </div>
              ))}
            </CardContent>
          </Card>
        </section>

        <DecisionDetails />
      </div>
    </main>
  );
}
