import { useEffect, useState } from "react";
import type { MouseEvent, ReactNode, TouchEvent } from "react";
import type { LedgerLaneExample } from "@/server/ledger-lane-example";

const GRID_IMAGE = "linear-gradient(rgba(119,212,255,0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(119,212,255,0.08) 1px, transparent 1px)";
const cx = (...parts: Array<string | false | null | undefined>) => parts.filter(Boolean).join(" ");

function GlowCard({ className = "", children }: { className?: string; children: ReactNode }) {
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [active, setActive] = useState(false);
  const moveTo = (clientX: number, clientY: number, element: HTMLElement) => {
    const rect = element.getBoundingClientRect();
    setPosition({ x: clientX - rect.left, y: clientY - rect.top });
  };
  const handleMouseMove = (event: MouseEvent<HTMLDivElement>) => moveTo(event.clientX, event.clientY, event.currentTarget);
  const handleTouch = (event: TouchEvent<HTMLDivElement>) => {
    const touch = event.touches[0];
    if (touch) { moveTo(touch.clientX, touch.clientY, event.currentTarget); setActive(true); }
  };
  const gridMask = `radial-gradient(230px circle at ${position.x}px ${position.y}px, black, transparent 76%)`;
  return (
    <article onMouseMove={handleMouseMove} onMouseEnter={() => setActive(true)} onMouseLeave={() => setActive(false)} onTouchStart={handleTouch} onTouchMove={handleTouch} onTouchEnd={() => setActive(false)} className={cx("campaign-card relative overflow-hidden rounded-[28px]", className)}>
      <div aria-hidden="true" className="absolute inset-0 rounded-[28px] bg-white/10" />
      <div aria-hidden="true" className={cx("absolute inset-0 rounded-[28px] transition-opacity duration-500", active ? "opacity-100" : "opacity-0")} style={{ background: `radial-gradient(250px circle at ${position.x}px ${position.y}px, rgba(119,212,255,0.72), transparent 72%)` }} />
      <div aria-hidden="true" className="absolute inset-px overflow-hidden rounded-[27px] bg-[#07111f]">
        <div className={cx("absolute inset-0 transition-opacity duration-500", active ? "opacity-100" : "opacity-0")} style={{ background: `radial-gradient(390px circle at ${position.x}px ${position.y}px, rgba(119,212,255,0.12), transparent 66%)` }} />
        <div className={cx("absolute inset-0 transition-opacity duration-500", active ? "opacity-100" : "opacity-0")} style={{ backgroundImage: GRID_IMAGE, backgroundSize: "26px 26px", maskImage: gridMask, WebkitMaskImage: gridMask }} />
      </div>
      <div className="relative z-10 flex h-full flex-col p-5 sm:p-6">{children}</div>
    </article>
  );
}

function CardHeading({ number, title }: { number: string; title: string }) {
  return <div className="mb-5 flex items-center gap-3"><span className="flex h-7 w-7 items-center justify-center rounded-full border border-[#77D4FF]/25 bg-[#77D4FF]/10 text-[10px] font-semibold text-[#77D4FF]">{number}</span><h3 className="text-sm font-medium text-white">{title}</h3></div>;
}
function ExampleLabel({ readOnly = false }: { readOnly?: boolean }) {
  return <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-[10px] font-medium uppercase tracking-[0.16em] text-slate-300"><i className="h-1.5 w-1.5 rounded-full bg-[#FF4CAB]" />{readOnly ? "Read-only example" : "Example campaign"}</span>;
}
function DraftBadge() { return <span className="rounded-full border border-[#77D4FF]/20 bg-[#77D4FF]/10 px-2.5 py-1 text-[10px] font-medium text-[#77D4FF]">Draft</span>; }

function WebsiteCard({ example }: { example: LedgerLaneExample }) {
  return <GlowCard className="min-h-[390px] lg:col-span-2">
    <CardHeading number="01" title="Start with your website" />
    <div className="rounded-2xl border border-white/10 bg-[#030914]/80 p-3"><div className="flex items-center gap-2 rounded-xl border border-[#77D4FF]/15 bg-[#07111f] px-3 py-2.5 text-xs text-slate-300"><span className="h-2 w-2 shrink-0 rounded-full bg-[#77D4FF] shadow-[0_0_10px_rgba(119,212,255,0.7)]" /><span className="min-w-0 truncate">{example.brand.website}</span></div></div>
    <div className="mt-4 flex flex-1 flex-col justify-between rounded-2xl border border-white/10 bg-gradient-to-br from-[#0b1d31] to-[#050914] p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-[10px] uppercase tracking-[0.18em] text-[#77D4FF]">Saved brand profile</p><h4 className="mt-2 text-2xl font-semibold tracking-tight text-white">{example.brand.name}</h4></div><ExampleLabel /></div>
      <p className="my-6 max-w-md text-sm leading-6 text-slate-300">{example.brand.description}</p>
      <div><p className="mb-3 text-[10px] uppercase tracking-[0.16em] text-slate-500">Saved brand colours · {example.brand.fontStyle} type</p><div className="flex gap-2" aria-label={`${example.brand.name} brand colours`}>{example.brand.colours.map((colour) => <span key={colour} className="h-9 w-14 rounded-lg border border-white/10" style={{ backgroundColor: colour }} title={colour} />)}</div></div>
    </div>
  </GlowCard>;
}

function MetaCard({ example }: { example: LedgerLaneExample }) {
  return <GlowCard className="min-h-[680px] lg:col-span-2 lg:row-span-2">
    <div className="flex items-start justify-between gap-4"><CardHeading number="02" title="Meta creative" /><DraftBadge /></div>
    <div className="flex flex-1 flex-col items-center justify-center rounded-2xl border border-white/10 bg-[#030914]/70 p-3 sm:p-5">
      <div data-testid="ledger-lane-creative" className="w-full max-w-[360px] overflow-hidden rounded-[20px] border border-white/10 bg-[#f5f0e6] shadow-[0_26px_70px_rgba(0,0,0,0.38)]" style={{ aspectRatio: example.metaCreative.aspectRatio }}>
        <img src={example.metaCreative.assetUrl} alt="Ledger Lane advert with ledgers, headline and consultation call to action" width="1792" height="2400" className="h-full w-full object-contain" />
      </div>
    </div>
    <div className="mt-4"><p className="text-base font-medium text-white">{example.metaCreative.headline}</p><div className="mt-2 flex flex-wrap items-center gap-2"><p className="text-xs text-slate-400">{example.metaCreative.supportingLine}</p><span className="rounded-full border border-white/10 bg-white/[0.05] px-2.5 py-1 text-[10px] font-medium text-white">{example.metaCreative.callToAction}</span></div></div>
  </GlowCard>;
}

function SocialCard({ example }: { example: LedgerLaneExample }) {
  return <GlowCard className="min-h-[290px] lg:col-span-2">
    <div className="flex items-start justify-between gap-4"><CardHeading number="03" title="Social post" /><DraftBadge /></div>
    <div className="grid flex-1 gap-4 rounded-2xl border border-white/10 bg-[#030914]/70 p-4 sm:grid-cols-[118px_1fr] sm:items-center">
      <img src={example.metaCreative.assetUrl} alt="Ledger Lane saved social creative" width="1792" height="2400" className="mx-auto aspect-[1792/2400] w-[118px] rounded-xl object-contain" />
      <div><p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#77D4FF]">{example.brand.name} · {example.social.channel}</p><p className="mt-3 text-sm leading-6 text-slate-300">{example.social.caption}</p></div>
    </div>
  </GlowCard>;
}

function WorkspaceCard({ example }: { example: LedgerLaneExample }) {
  const assets = [
    { type: "Meta creative", title: example.metaCreative.headline, detail: "Original campaign advert" },
    { type: `${example.social.channel} post`, title: example.metaCreative.supportingLine, detail: "Saved campaign copy" },
  ];
  return <GlowCard className="min-h-[330px] lg:col-span-4">
    <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between"><CardHeading number="04" title="Campaign workspace" /><ExampleLabel readOnly /></div>
    <div className="mb-5 flex flex-col gap-1 border-b border-white/10 pb-5 sm:flex-row sm:items-end sm:justify-between"><div><p className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Saved campaign</p><h4 className="mt-1 text-2xl font-semibold tracking-tight text-white">{example.campaign.name}</h4></div><span className="mt-2 text-xs text-slate-400 sm:mt-0">{example.campaign.assetCount} saved outputs · goal: {example.campaign.goal}</span></div>
    <div className="grid flex-1 grid-cols-1 gap-3 md:grid-cols-2">{assets.map((asset, index) => <div key={asset.type} className="flex min-h-[150px] flex-col rounded-2xl border border-white/10 bg-[#030914]/70 p-4"><div className="flex items-center justify-between gap-3"><span className="text-xs font-medium text-slate-300">{asset.type}</span><DraftBadge /></div><div className="my-4 flex min-h-[148px] flex-1 items-center rounded-xl bg-white/[0.025] p-3">{index === 0 ? <img src={example.metaCreative.assetUrl} alt="Saved Ledger Lane campaign artwork" width="1792" height="2400" className="mx-auto h-[148px] w-auto rounded-lg object-contain" /> : <p className="text-sm leading-6 text-slate-300">{example.social.caption}</p>}</div><p className="text-sm font-medium text-white">{asset.title}</p><p className="mt-1 text-[10px] text-slate-500">{asset.detail}</p></div>)}</div>
  </GlowCard>;
}

function LoadingCard({ message }: { message: string }) { return <GlowCard className="min-h-[240px] lg:col-span-4"><div className="flex h-full items-center justify-center text-sm text-slate-400">{message}</div></GlowCard>; }

export default function CampaignBento({ initialExample }: { initialExample?: LedgerLaneExample }) {
  const [example, setExample] = useState<LedgerLaneExample | undefined>(initialExample);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (initialExample) return;
    const controller = new AbortController();
    fetch("/api/examples/ledger-lane", { signal: controller.signal }).then((response) => { if (!response.ok) throw new Error("Example unavailable"); return response.json() as Promise<LedgerLaneExample>; }).then(setExample).catch((error: unknown) => { if (!(error instanceof DOMException && error.name === "AbortError")) setFailed(true); });
    return () => controller.abort();
  }, [initialExample]);
  return <>
    <style>{`@media (prefers-reduced-motion: reduce) { .campaign-card *, .campaign-card *::before, .campaign-card *::after { animation: none !important; transition: none !important; } }`}</style>
    <section className="w-full border-t border-white/[0.06] bg-[#020617] px-4 py-16 text-slate-200 sm:px-8 sm:py-24"><div className="mx-auto max-w-6xl">
      <div className="mb-10 max-w-3xl sm:mb-14"><ExampleLabel /><h2 className="mt-5 text-3xl font-semibold tracking-[-0.04em] text-white sm:text-5xl">From your website to your next campaign</h2><p className="mt-4 max-w-2xl text-base leading-7 text-slate-400 sm:text-lg">Add your website, then create Meta ads, social posts and emails tailored to your business.</p></div>
      <div className="grid grid-cols-1 gap-4 lg:auto-rows-[minmax(390px,auto)] lg:grid-cols-4">{example ? <><WebsiteCard example={example} /><MetaCard example={example} /><SocialCard example={example} /><WorkspaceCard example={example} /></> : <LoadingCard message={failed ? "The example campaign is temporarily unavailable." : "Loading the saved Ledger Lane campaign…"} />}</div>
    </div></section>
  </>;
}
