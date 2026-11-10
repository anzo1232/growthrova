"""Ephemeral Chromium worker. stdout is a bounded parent-broker IPC protocol.

No application imports or ambient credentials. Never use route.fetch/continue_,
which would give the browser its own network transport.
"""
import base64
import html
import json
import sys

CSP="default-src 'none'; script-src https: 'unsafe-inline' 'unsafe-eval'; style-src https: 'unsafe-inline'; connect-src https:; img-src 'none'; font-src 'none'; media-src 'none'; frame-src 'none'; worker-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"

def emit(value):
    sys.stdout.write(json.dumps(value)+'\n');sys.stdout.flush()


STAGE='runtime_import'

def main():
    global STAGE
    from playwright.sync_api import sync_playwright
    config=json.loads(sys.stdin.readline(8192))
    timeout=min(20000,max(1,config['timeout_ms']))
    with sync_playwright() as playwright:
        STAGE='sandbox_launch'
        browser=playwright.chromium.launch(headless=True,chromium_sandbox=True,
            executable_path=config.get('browser'),timeout=timeout,
            proxy={'server':config['proxy'],'bypass':'<-loopback>'},
            args=['--disable-quic','--disable-background-networking','--disable-component-update',
                  '--disable-domain-reliability','--dns-prefetch-disable',
                  '--host-resolver-rules=MAP * ~NOTFOUND',
                  '--force-webrtc-ip-handling-policy=disable_non_proxied_udp'])
        STAGE='context_setup'
        context=browser.new_context(service_workers='block',accept_downloads=False,
            ignore_https_errors=False,permissions=[],java_script_enabled=True)
        context.set_default_timeout(timeout)
        # Missing route_web_socket (Playwright <1.48) fails closed before navigation.
        context.route_web_socket('**/*',lambda ws:ws.close())
        context.add_init_script("""for (const name of ['RTCPeerConnection','webkitRTCPeerConnection','WebTransport']) {
          Object.defineProperty(globalThis,name,{value:undefined,writable:false,configurable:false});
        }""")
        page=context.new_page()
        page.on('download',lambda download:download.cancel())
        page.on('framenavigated',lambda frame:page.close() if frame==page.main_frame and frame.url!=config['url'] else None)
        context.on('page',lambda popup:popup.close() if popup!=page else None)
        initial_document=[False]
        def route_request(route):
            request=route.request
            kind=request.resource_type
            if (request.method!='GET' or kind not in ('document','script','stylesheet','fetch','xhr') or
                request.url.split(':',1)[0]!='https' or
                (kind=='document' and (request.frame!=page.main_frame or initial_document[0]))):
                route.abort('blockedbyclient');return
            if kind=='document':initial_document[0]=True
            emit({'type':'request','url':request.url,'kind':kind})
            reply=json.loads(sys.stdin.readline(4*1024*1024))
            if reply.get('error'):
                route.abort('blockedbyclient');return
            route.fulfill(status=200,body=base64.b64decode(reply['body'],validate=True),
                headers={'Content-Type':reply['mime'],'Content-Security-Policy':CSP,
                         'X-Content-Type-Options':'nosniff','Cache-Control':'no-store'})
        context.route('**/*',route_request)
        STAGE='page_render'
        page.goto(config['url'],wait_until='domcontentloaded',timeout=timeout)
        # Wait for hydrated business content, rather than networkidle (tracking and
        # persistent polling must not consume the rendering deadline).
        try:
            page.wait_for_function("""() => [...document.querySelectorAll('h1,h2,h3,p')]
              .filter(e=>e.getClientRects().length && e.innerText.trim().length>24).length>=2""",
              timeout=min(6000,timeout))
        except Exception as exc:
            from playwright.sync_api import TimeoutError
            if not isinstance(exc,TimeoutError):raise
        snapshot=page.evaluate(r"""() => {
          const visible=e=>e.getClientRects().length && getComputedStyle(e).visibility!=='hidden';
          const text=e=>(e.innerText||'').replace(/\\s+/g,' ').trim();
          const nodes=[...document.querySelectorAll('h1,h2,h3,p,a,img')].filter(visible).slice(0,400);
          const items=nodes.map(e=>({tag:e.tagName.toLowerCase(),text:text(e).slice(0,1200),
            href:e.tagName==='A'?e.href:'',src:e.tagName==='IMG'?e.src:'',alt:e.alt||''}));
          // Applications sometimes use div/span blocks instead of paragraphs.
          if(!items.some(x=>x.tag==='p' && x.text.length>=24)) {
            for(const e of [...document.querySelectorAll('main div,main section,main span,#root div,#app div')]
              .filter(visible).filter(e=>!e.children.length).slice(0,80)) {
              const words=text(e);if(words.length>=24)items.push({tag:'p',text:words.slice(0,1200)});
            }
          }
          const rgbHex=value=>{const m=String(value||'').match(/^rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)$/);if(!m||m[4]==='0')return '';return '#'+[m[1],m[2],m[3]].map(x=>(+x).toString(16).padStart(2,'0')).join('').toUpperCase();};
          const colourCounts=new Map(),fontCounts=new Map();
          const add=(map,key)=>{if(key)map.set(key,(map.get(key)||0)+1);};
          const styled=[document.body,...nodes].filter(Boolean).slice(0,401);
          for(const e of styled){const st=getComputedStyle(e);for(const key of ['color','backgroundColor','borderTopColor'])add(colourCounts,rgbHex(st[key]));const family=(st.fontFamily||'').split(',')[0].replace(/["']/g,'').trim();if(text(e).length>=2)add(fontCounts,family);}
          const bodyStyle=getComputedStyle(document.body);
          const bodyBackground=rgbHex(bodyStyle.backgroundColor),bodyText=rgbHex(bodyStyle.color);
          const logoCandidates=[];
          const addLogo=item=>{if(item&&!logoCandidates.some(x=>JSON.stringify(x)===JSON.stringify(item))&&logoCandidates.length<4)logoCandidates.push(item);};
          for(const e of [...document.querySelectorAll('img')].filter(visible)){
            const clue=((e.alt||'')+' '+(e.className||'')+' '+(e.id||'')).toLowerCase();
            if(/logo|brand/.test(clue)&&e.src)addLogo({kind:'image_url',url:e.src,description:(e.alt||'Visible website logo').slice(0,120)});
          }
          for(const e of [...document.querySelectorAll('[class*="logo" i] svg,[id*="logo" i] svg,nav svg,header svg')].filter(visible)){
            const markup=e.outerHTML;if(markup&&markup.length<=32768)addLogo({kind:'inline_svg',svg:markup,description:'Visible inline website logo'});
          }
          for(const node of [...document.querySelectorAll('script[type="application/ld+json"]')].slice(0,8)){
            try{const walk=value=>{if(!value||typeof value!=='object')return;if(typeof value.logo==='string')addLogo({kind:'image_url',url:new URL(value.logo,document.baseURI).href,description:'Structured-data organisation logo'});else if(value.logo&&typeof value.logo.url==='string')addLogo({kind:'image_url',url:new URL(value.logo.url,document.baseURI).href,description:'Structured-data organisation logo'});for(const child of Object.values(value))if(child&&typeof child==='object')walk(child);};walk(JSON.parse(node.textContent));}catch{}
          }
          return {title:document.title.slice(0,200),description:(document.querySelector('meta[name="description"]')?.content||'').slice(0,500),items,
            visualIdentity:{status:'website_observed_unconfirmed',background:bodyBackground,text:bodyText,
              colours:[...colourCounts].sort((a,b)=>b[1]-a[1]).slice(0,12).map(([hex,count])=>({hex,count})),
              fontFamilies:[...fontCounts].sort((a,b)=>b[1]-a[1]).slice(0,6).map(([family,count])=>({family,count})),
              logoCandidates}};
        }""")
        esc=lambda value:html.escape(value or '',quote=True)
        parts=['<title>'+esc(snapshot['title'])+'</title>',
               '<meta name="description" content="'+esc(snapshot['description'])+'">']
        for item in snapshot['items']:
            tag=item['tag']
            if tag=='img':parts.append('<img src="'+esc(item['src'])+'" alt="'+esc(item['alt'])+'">')
            elif tag=='a':parts.append('<a href="'+esc(item['href'])+'">'+esc(item['text'])+'</a>')
            elif tag in ('p','h1','h2','h3'):parts.append('<'+tag+'>'+esc(item['text'])+'</'+tag+'>')
        emit({'type':'result','html':''.join(parts),'visual_identity':snapshot['visualIdentity']})
        context.close();browser.close()

if __name__=='__main__':
    try:main()
    except Exception:emit({'type':'error','stage':STAGE}) # Never emit environment, paths or page code.
