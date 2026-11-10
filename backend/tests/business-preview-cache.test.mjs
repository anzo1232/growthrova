import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve, relative, sep} from 'node:path';
import {resolveConfig} from 'vite';
import standalone from '../vite.growthrova.config.js';

test('standalone development resolves its writable dependency cache inside its own output', async()=>{
  // Resolve the actual dev configuration before starting an optimizer. The
  // shared node_modules symlink must never receive Growthrova cache writes.
  const config=await resolveConfig({configFile:'vite.growthrova.config.js'},'serve');
  const output=resolve(config.root,config.build.outDir);
  const cache=relative(output,config.cacheDir);
  assert.ok(cache && cache!=='..' && !cache.startsWith('..'+sep),
    'Growthrova dependency cache must be inside its isolated build output');
  assert.equal(standalone.envDir,false);
  assert.equal(config.build.rollupOptions.input,'growthrova.html');
});
