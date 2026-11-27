(() => {
  // O HTML do topo é reemitido pelo Streamlit; o listener é único por página.
  if (window.__settaFechamentoNavigation) return;
  window.__settaFechamentoNavigation = true;
  const root = document.documentElement;
  const bodySelector = '[data-testid="stMainBlockContainer"]';
  const renderedRoute = () => document.querySelector('.setta-inv-intro')?.dataset.settaRoute;
  const busy = new Set(['running', 'rerunRequested', 'stopRequested']);
  let pending = null;
  let frame = 0;

  // Abrir o menu é só uma mudança visual local: nenhum evento vai ao Python.
  const toggleSelector = '.setta-drawer-toggle';
  const sidebarSelector = '[data-testid="stSidebar"]';
  const drawerOpen = () => root.hasAttribute('data-setta-drawer-open');
  function syncDrawer() {
    const button = document.querySelector(toggleSelector);
    const sidebar = document.querySelector(sidebarSelector);
    const open = drawerOpen();
    if (sidebar) {
      sidebar.id = 'setta-fechamento-sidebar';
      sidebar.inert = !open;
    }
    if (button) {
      button.setAttribute('aria-expanded', String(open));
      button.setAttribute('aria-label', open ? 'Fechar menu lateral' : 'Abrir menu lateral');
    }
  }
  function setDrawer(open) {
    root.toggleAttribute('data-setta-drawer-open', open);
    syncDrawer();
  }
  syncDrawer();

  // Remove somente as instruções de teclado, sem alterar os eventos dos
  // campos nem os contadores de caracteres que o Streamlit exibe junto.
  const inputHint = '[data-testid="InputInstructions"]';
  const keyboardHint = /^Press (?:⌘\+|Ctrl\+)?Enter to (?:apply|submit(?: form)?)$/;
  function updateInputHint(group) {
    for (const child of group.children) {
      child.toggleAttribute('data-setta-keyboard-hint', keyboardHint.test(child.textContent.trim()));
    }
  }
  function inspectInputHints(node) {
    const element = node instanceof Element ? node : node.parentElement;
    if (!element) return;
    const group = element.closest(inputHint);
    if (group) updateInputHint(group);
    if (node instanceof Element) node.querySelectorAll(inputHint).forEach(updateInputHint);
  }
  document.querySelectorAll(inputHint).forEach(updateInputHint);
  new MutationObserver(records => {
    for (const record of records) {
      if (record.type === 'characterData') inspectInputHints(record.target);
      else {
        const group = record.target instanceof Element && record.target.closest(inputHint);
        if (group) updateInputHint(group);
        for (const node of record.addedNodes) {
          if (!(node instanceof Element)) continue;
          inspectInputHints(node);
          if (node.matches(toggleSelector + ',' + sidebarSelector) ||
              node.querySelector(toggleSelector + ',' + sidebarSelector)) syncDrawer();
        }
      }
    }
  }).observe(document.body, {subtree: true, childList: true, characterData: true});

  function finish() {
    pending = null;
    delete root.dataset.settaInventoryNavigating;
  }

  function watch() {
    if (frame || !pending) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      if (!pending) return;
      const work = document.querySelector(bodySelector);
      const state = document.querySelector('[data-testid="stApp"]')?.dataset.testScriptState;
      const running = busy.has(state);
      const stale = !!work?.querySelector('[data-stale="true"]');
      const elapsed = performance.now() - pending.start;
      if (running || stale) pending.sawRender = true;
      // O novo título pode ser entregue antes do corpo da tela. Não abre a
      // máscara antes de o Streamlit terminar e remover os elementos antigos.
      if ((!running && !stale &&
            (renderedRoute() === pending.target || (pending.sawRender && elapsed > 2200) ||
             (!pending.sawRender && elapsed > 1500))) ||
          state === 'compilationError' || elapsed > 25_000) {
        finish();
        return;
      }
      watch();
    });
  }

  document.addEventListener('click', event => {
    if (!(event.target instanceof Element)) return;
    if (event.target.closest(toggleSelector)) {
      setDrawer(!drawerOpen());
      return;
    }
    const button = event.target.closest('.st-key-setta_route_list button');
    if (!button || button.disabled || !renderedRoute()) return;
    const wrapper = button.closest('[class*="st-key-setta_nav_"]');
    const key = [...(wrapper?.classList || [])].find(s => /^st-key-setta_nav_\d+$/.test(s));
    const target = key?.split('_').at(-1);
    if (!target) return;
    setDrawer(false);
    document.querySelector(toggleSelector)?.focus({preventScroll:true});
    if (!pending && target === renderedRoute()) {
      // O item ativo fecha o painel, sem mandar recarregar a mesma tela.
      event.stopPropagation();
      return;
    }
    if (target === pending?.target) return;
    pending = { target, start: performance.now(), sawRender: false };
    root.dataset.settaInventoryNavigating = 'true';
    watch();
  }, true);

  document.addEventListener('keydown', event => {
    if (event.defaultPrevented || event.key !== 'Escape' || !drawerOpen()) return;
    if (!(event.target instanceof Element) ||
        !event.target.closest(sidebarSelector + ',' + toggleSelector)) return;
    setDrawer(false);
    document.querySelector(toggleSelector)?.focus({preventScroll:true});
  });
})();
