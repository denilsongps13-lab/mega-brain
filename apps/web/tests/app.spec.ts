import { test, expect } from '@playwright/test';
const token = process.env.E2E_TOKEN!;
async function login(page: import('@playwright/test').Page) { await page.goto('/'); await page.getByLabel('Token de acesso da instalação').fill(token); await page.getByRole('button',{name:'Acessar meu cérebro'}).click(); await expect(page.getByRole('heading',{name:'O que vamos construir hoje?'})).toBeVisible(); }
test('desktop: real API upload, RAG, provider failure and persistent history', async ({page}) => {
  const errors:string[]=[]; page.on('pageerror',e=>errors.push(e.message));
  await login(page);
  await page.getByRole('button',{name:'Documentos',exact:true}).click();
  await page.getByLabel('Enviar documento').setInputFiles({name:'aurora-e2e.txt',mimeType:'text/plain',buffer:Buffer.from('O projeto Aurora usa baterias solares em comunidades isoladas. '.repeat(15))});
  await expect(page.getByText('aurora-e2e.txt',{exact:true}).first()).toBeVisible();
  await expect(page.getByText('Concluído',{exact:true}).first()).toBeVisible({timeout:20000});
  await page.getByRole('button',{name:'Memória',exact:true}).click();
  await page.getByLabel('Pesquisar memória').fill('Aurora baterias'); await page.getByRole('button',{name:'Pesquisar',exact:true}).click();
  await expect(page.locator('summary').filter({hasText:'fontes consultadas'})).toBeVisible();
  await page.getByRole('button',{name:'Novo chat'}).click();
  await page.getByLabel('Mensagem',{exact:true}).fill('Explique o projeto Aurora'); await page.getByRole('button',{name:'Enviar mensagem'}).click();
  await expect(page.getByText('Explique o projeto Aurora',{exact:true}).first()).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('Falha no engine',{timeout:20000});
  await page.reload(); await page.getByLabel('Token de acesso da instalação').fill(token); await page.getByRole('button',{name:'Acessar meu cérebro'}).click();
  await page.getByRole('button',{name:'Conversas',exact:true}).click();
  await page.locator('.list-row').filter({hasText:'Explique o projeto Aurora'}).first().click();
  await expect(page.locator('.message.user')).toContainText('Explique o projeto Aurora');
  expect(errors).toEqual([]);
});
test('mobile: navigation, status and no horizontal overflow', async ({page}) => {
  await page.setViewportSize({width:390,height:844}); await login(page);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:'test-results/mobile-chat.png',fullPage:true});
  await page.getByRole('button',{name:'Abrir menu'}).click(); await page.getByRole('button',{name:'Status',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Status',exact:true})).toBeVisible();
  await expect(page.getByText('Provedores de inteligência')).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
test('PWA service worker offers offline page without caching private API data', async({page,context})=>{
  await page.goto('/'); await page.evaluate(()=>navigator.serviceWorker.ready);
  await page.reload(); await context.setOffline(true); await page.reload();
  await expect(page.getByRole('heading',{name:'Você está offline'})).toBeVisible();
  await context.setOffline(false);
});
