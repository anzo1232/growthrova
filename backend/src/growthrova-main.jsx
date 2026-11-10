import React from 'react';
import {createRoot} from 'react-dom/client';
import {createClient} from '@supabase/supabase-js';
import {growthrovaProjectConfig} from './lib/growthrovaTransport.mjs';
import GrowthrovaWorkspace from './GrowthrovaWorkspace.jsx';
try {
  const {url,key}=growthrovaProjectConfig(import.meta.env.VITE_GROWTHROVA_SUPABASE_URL,import.meta.env.VITE_GROWTHROVA_SUPABASE_ANON_KEY);
  const client=createClient(url,key,{auth:{storageKey:'growthrova-isolated-session',detectSessionInUrl:false}});
  createRoot(document.getElementById('root')).render(<GrowthrovaWorkspace client={client} presentation="product"/>);
}catch(error){document.getElementById('root').textContent=error.message;}
