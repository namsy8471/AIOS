import { spawn, spawnSync } from 'node:child_process';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const devkit = resolve(process.env.AIOS_SIWC_DIR || join(root, 'build/sdk/sign-in-with-chatgpt-devkit'));
const storage = resolve(process.env.LOCALAPPDATA || homedir(), 'AIOS', 'ChatGPT');

function dpapi(operation, bytes) {
  const protectedData = spawnSync('pwsh.exe', ['-NoProfile', '-NonInteractive', '-File',
    join(root, 'scripts/mobile-credential.ps1'), operation], {
    input: Buffer.from(bytes).toString('base64'), encoding: 'ascii', windowsHide: true,
  });
  if (protectedData.status !== 0) throw new Error('Windows credential storage failed');
  return Buffer.from(protectedData.stdout, 'base64');
}

async function main() {
  const { createChatGPT } = await import(pathToFileURL(join(devkit, 'packages/local/dist/index.js')).href);
  const client = createChatGPT({
    appName: 'AIOS', appId: 'org.aios.mobile', redirectPort: 0, storageDir: storage, sendHostId: true,
    credentialEncryption: {
      id: 'aios-windows-dpapi-v1', isAvailable: () => process.platform === 'win32',
      encrypt: (value) => dpapi('protect', Buffer.from(value, 'utf8')),
      decrypt: (value) => dpapi('unprotect', value).toString('utf8'),
    },
    openBrowser(url) {
      const target = new URL(url);
      if (target.origin !== 'https://auth.openai.com') throw new Error('Unexpected ChatGPT sign-in host');
      return new Promise((done, reject) => {
        const browser = spawn('rundll32.exe', ['url.dll,FileProtocolHandler', target.href], { stdio: 'ignore' });
        browser.once('error', reject);
        browser.once('spawn', () => { browser.unref(); done(); });
      });
    },
  });
  const mode = process.argv[2];
  if (mode === 'connect' || mode === 'status') {
    const session = mode === 'connect' ? await client.signIn() : await client.getSession();
    console.log(JSON.stringify({ status: session.status, plan_usage: session.sharing }));
  } else if (mode === 'disconnect') {
    await client.disconnect();
    console.log(JSON.stringify({ status: 'disconnected' }));
  } else if (mode === 'draft') {
    let input = '';
    process.stdin.setEncoding('utf8');
    for await (const chunk of process.stdin) {
      input += chunk;
      if (Buffer.byteLength(input) > 65536) throw new Error('Draft request too large');
    }
    const job = JSON.parse(input);
    const selected = process.env.AIOS_CHATGPT_MODEL;
    const signal = AbortSignal.timeout(105000);
    const models = await client.listModels({ signal });
    const model = selected ? models.find((item) => item.slug === selected) : models[0];
    if (!model) throw new Error('No configured model is available on this ChatGPT plan');
    const response = await client.streamResponse({ model: model.slug, input: job.input, instructions: job.instructions, signal });
    console.log(JSON.stringify({ model: model.slug, text: response.text }));
  } else {
    throw new Error('Expected connect, status, disconnect or draft');
  }
}

main().catch((error) => {
  console.error(JSON.stringify({ error: error.code || 'chatgpt_connection_failed' }));
  process.exitCode = 1;
});
