(() => {
  // O HTML do topo é reemitido pelo Streamlit; o listener é único por página.
  const assetVersion = 4;
  if (window.__settaFechamentoNavigation?.version === assetVersion) return;
  const previous = window.__settaFechamentoNavigation;
  if (previous === true) return; // Live sessions running the legacy script switch on refresh.
  previous?.dispose?.();
  const controller = new AbortController();
  window.__settaFechamentoNavigation = {version: assetVersion, dispose};
  const listen = (type, listener, capture = false) =>
    document.addEventListener(type, listener, {capture, signal: controller.signal});
  const root = document.documentElement;
  const routeSelector = '[class*="st-key-fm_route_body_"]';
  const renderedRoute = () => document.querySelector('.setta-inv-intro')?.dataset.settaRoute;
  const busy = new Set(['running', 'rerunRequested', 'stopRequested']);
  let page = null;
  let op = null;
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
  const hintObserver = new MutationObserver(records => {
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
  });
  hintObserver.observe(document.body, {subtree: true, childList: true, characterData: true});
  function dispose() {
    controller.abort();
    hintObserver.disconnect();
    if (frame) cancelAnimationFrame(frame);
    runObserver.disconnect();
    finishPage();
    finishOp(false);
  }

  const staleSelector = '[data-stale="true"]';
  const marker = (selector) => document.querySelector(selector);
  const live = (node) => node && !node.closest(staleSelector);
  const appState = () => marker('[data-testid="stApp"]')?.dataset.testScriptState;
  const stable = (job, condition) => {
    job.frames = condition ? (job.frames || 0) + 1 : 0;
    return job.frames >= 2;
  };
  function finishPage() {
    page = null;
    delete root.dataset.settaPageUpdating;
    delete root.dataset.settaPageSwitching;
    delete root.dataset.settaNavPlaceholder;
  }
  function finishOp(animate) {
    if (animate && op?.target) {
      marker('.st-key-fm_issue_op_detail_' + op.target)?.setAttribute('data-setta-op-entering', '');
    }
    op = null;
    delete root.dataset.settaOpTransition;
    delete root.dataset.settaOpPlaceholder;
  }
  function pageSurface() {
    const route = renderedRoute();
    return route === undefined ? null : marker('.st-key-fm_route_body_' + route);
  }
  const isStale = (wrapper) => wrapper && (!live(wrapper) || wrapper.querySelector(staleSelector));
  function beginPage(target = null) {
    if (!page && target === null && !pageSurface()) return;
    page = { target, start: performance.now(), started: busy.has(appState()) };
    root.dataset.settaPageUpdating = 'true';
    root.toggleAttribute('data-setta-page-switching', target !== null);
    delete root.dataset.settaNavPlaceholder;
    watch();
  }

  // Run-state changes arrive before the next paint, including reruns from
  // selects, calendars, forms, grid selections, and server-side callbacks.
  // No list of controls to maintain, and pure UI clicks never show a loader.
  function observeRun() {
    const running = busy.has(appState());
    if (page) {
      if (running) page.started = true;
      return;
    }
    if (op) {
      if (running) op.started = true;
      return;
    }
    const surface = pageSurface();
    if (surface && (running || isStale(surface))) beginPage();
  }
  const runObserver = new MutationObserver(observeRun);
  runObserver.observe(document.body, {
    subtree: true, childList: true, attributes: true,
    attributeFilter: ['data-test-script-state', 'data-stale'],
  });
  observeRun();

  function watch() {
    if (frame || (!page && !op)) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      const state = appState();
      const running = busy.has(state);
      const error = state === 'compilationError' || !!marker('[data-testid="stException"]');
      const now = performance.now();
      if (page) {
        const elapsed = now - page.start;
        const current = renderedRoute();
        const wrapper = pageSurface();
        const ready = wrapper?.querySelector('[data-setta-aba-pronta="' + current + '"]');
        if (elapsed > 150) root.dataset.settaNavPlaceholder = 'true';
        if (stable(page, !running && (error || (
            (page.target === null || current === page.target) && live(ready) && !isStale(wrapper)
        )))) {
          finishPage();
        } else if (!running && elapsed > (!page.started ? 900 : 2500)) {
          // A dropped click, interrupted run or server error must not leave a
          // permanent mask. Stale nodes still cannot be shown or clicked.
          finishPage();
        }
      }
      if (op) {
        const elapsed = now - op.start;
        const ready = marker('[data-setta-op-pronta]');
        const list = marker('.st-key-fm_issue_ops');
        if (elapsed > 150) root.dataset.settaOpPlaceholder = 'true';
        const complete = !running && live(ready) && ready.dataset.settaOpPronta === op.target
          && list && !isStale(list);
        if (stable(op, complete)) finishOp(true);
        else if (!running && (error || elapsed > (op.started ? 2500 : 900))) finishOp(false);
      }
      watch();
    });
  }
  listen('click', event => {
    if (!(event.target instanceof Element)) return;
    if (event.target.closest(toggleSelector)) {
      setDrawer(!drawerOpen());
      return;
    }
    const opButton = event.target.closest('[class*="st-key-fm_issue_select_"] button');
    if (!page && opButton && !opButton.disabled) {
      const wrap = opButton.closest('[class*="st-key-fm_issue_select_"]');
      const id = [...wrap.classList].find(k => /^st-key-fm_issue_select_[0-9]+$/.test(k))?.split('_').at(-1);
      const current = marker('[data-setta-op-pronta]')?.dataset.settaOpPronta;
      if (id && current !== undefined) {
        document.querySelectorAll('[data-setta-op-entering]').forEach(el => el.removeAttribute('data-setta-op-entering'));
        op = {target: id === current ? '' : id, start: performance.now()};
        root.dataset.settaOpTransition = 'true';
        watch();
      }
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
    if (!page && target === renderedRoute()) {
      // O item ativo fecha o painel, sem mandar recarregar a mesma tela.
      event.stopPropagation();
      return;
    }
    if (target === page?.target) return;
    finishOp(false);
    beginPage(target);
    marker('[data-testid="stMain"]')?.scrollTo({top: 0, behavior: 'instant'});
  }, true);

  listen('keydown', event => {
    if (event.defaultPrevented || event.key !== 'Escape' || !drawerOpen()) return;
    if (!(event.target instanceof Element) ||
        !event.target.closest(sidebarSelector + ',' + toggleSelector)) return;
    setDrawer(false);
    document.querySelector(toggleSelector)?.focus({preventScroll:true});
  });
})();
