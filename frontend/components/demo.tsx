import Head from "next/head";
import Hero from "@/components/ui/animated-shader-hero";
import CampaignBento from "@/components/ui/campaign-bento";
import type { LedgerLaneExample } from "@/server/ledger-lane-example";

export default function HeroDemo({ initialExample }: { initialExample?: LedgerLaneExample }) {
  return <div className="w-full bg-[#020617] text-slate-200">
    <Head><title>Growthrova — Your marketing team, built in.</title><meta name="description" content="Turn your website into a marketing plan, creative and content you can review and manage in one workspace." /></Head>
    <a className="sr-only focus:not-sr-only focus:fixed focus:top-4 focus:left-4 z-50 rounded-lg bg-white p-4 text-slate-900" href="#examples">Skip to campaign example</a>
    <nav aria-label="Main navigation" className="absolute inset-x-0 top-0 z-20 flex items-center justify-end gap-6 px-6 py-5 sm:px-10">
      <a href="#examples" className="text-sm text-slate-200 hover:text-white">Example campaign</a>
      <a href="/app" className="rounded-full border border-sky-200/30 px-5 py-3 text-sm text-white hover:bg-sky-200/10">Sign in</a>
    </nav>
    <Hero wordmark="growthrova" headline={{line1:"Your marketing team,",line2:"built in."}}
      subtitle="Enter your website to create Meta ads, social posts, and emails tailored to your business."
      buttons={{primary:{text:"Create a Campaign",onClick:()=>{window.location.href="/app";}},
      secondary:{text:"See Example Campaigns",onClick:()=>{document.getElementById("examples")?.scrollIntoView({behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth"});}}}} />
    <div id="examples"><CampaignBento initialExample={initialExample} /></div>
    <section aria-labelledby="workflow-heading" className="mx-auto max-w-6xl px-6 py-20 sm:py-28">
      <p className="text-xs uppercase tracking-[.2em] text-[#77D4FF]">YOUR WORKFLOW</p>
      <h2 id="workflow-heading" className="mt-4 max-w-2xl text-3xl font-semibold tracking-tight sm:text-5xl">From your first idea<br />to your next campaign.</h2>
      <div className="mt-12 grid gap-10 sm:grid-cols-3">
        {[["01","Start with your website","Bring your business, offer and audience into one brief. Review the details before creating."],
          ["02","Find your direction","Explore concepts, refine your copy and generate artwork around your brand."],
          ["03","Keep everything together","Save campaigns, organise content and return to the exact work you left."]].map(([n,title,copy])=>
          <div key={n} className="border-t border-sky-100/15 pt-6"><span className="text-sm text-[#77D4FF]">{n}</span><h3 className="mt-5 text-xl font-medium text-white">{title}</h3><p className="mt-3 leading-7 text-slate-400">{copy}</p></div>)}
      </div>
    </section>
    <section className="border-y border-sky-100/10 bg-[radial-gradient(ellipse_at_top,rgba(119,212,255,.09),transparent_65%)] px-6 py-20 text-center">
      <h2 className="text-3xl font-semibold tracking-tight text-white sm:text-5xl">Your next campaign starts here.</h2>
      <p className="mx-auto mt-5 max-w-lg leading-7 text-slate-400">Bring your website. Build your brief. Make your next move.</p>
      <a href="/app" className="mt-8 inline-flex min-h-12 items-center rounded-full bg-[#77D4FF] px-8 py-4 font-semibold text-[#020617] hover:bg-white">Open your workspace <span aria-hidden="true" className="ml-4">↗</span></a>
    </section>
    <footer className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-6 px-6 py-9 text-sm text-slate-400"><a href="/" className="text-lg font-semibold tracking-tight text-white">growthrova</a><div className="flex gap-6"><a href="#examples">Campaign example</a><a href="/app">Your workspace</a></div></footer>
  </div>;
}
