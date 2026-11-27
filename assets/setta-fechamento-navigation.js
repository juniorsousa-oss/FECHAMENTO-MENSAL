(() => {
  // O HTML do topo é reemitido pelo Streamlit; o listener é único por página.
  const assetVersion = 3;
  if (window.__settaFechamentoNavigation?.version === assetVersion) return;
  const previous = window.__settaFechamentoNavigation;
  if (previous === true) return; // Live sessions running the legacy script switch on refresh.
  previous?.dispose?.();
  const controller = new AbortController();
  window.__settaFechamentoNavigation = {version: assetVersion, dispose};
  const listen = (type, listener, capture = false) =>
    document.addEventListener(type, listener, {capture, signal: controller.signal});
  const root = document.documentElement;
  const bodySelector = '[data-testid="stMainBlockContainer"]';
  const renderedRoute = () => document.querySelector('.setta-inv-intro')?.dataset.settaRoute;
  const busy = new Set(['running', 'rerunRequested', 'stopRequested']);
  let pending = null;
  let section = null;
  let op = null;
  const sectionKeys = [
    ['dashboard', '.st-key-fm_dashboard_detail'],
    ['chapas', '[class*="st-key-cb_visible_stage_"]'],
    ['kardex', '.st-key-fm_mov_navigation'],
    ['reports', '.st-key-fm_reports_kind'],
    ['settings', '.st-key-fm_settings_area'],
    ['history', '.st-key-fm_history_view'],
    ['feeders', '.st-key-fm_feeder_type'],
    ['ops_source', '.st-key-fm_ops_settings_view'],
  ];
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
    finishRoute();
    finishSection();
    finishOp(false);
  }

  const staleSelector = '[data-stale="true"]';
  const marker = (selector) => document.querySelector(selector);
  const live = (node) => node && !node.closest(staleSelector);
  const appIsBusy = () => busy.has(document.querySelector('[data-testid="stApp"]')?.dataset.testScriptState);
  const stable = (job, condition) => {
    job.frames = condition ? (job.frames || 0) + 1 : 0;
    return job.frames >= 2;
  };
  function finishRoute() {
    pending = null;
    delete root.dataset.settaInventoryNavigating;
    delete root.dataset.settaNavPlaceholder;
  }
  function finishSection() {
    section = null;
    delete root.dataset.settaSectionLoading;
  }
  function finishOp(animate) {
    if (animate && op?.target) {
      marker('.st-key-fm_issue_op_detail_' + op.target)?.setAttribute('data-setta-op-entering', '');
    }
    op = null;
    delete root.dataset.settaOpTransition;
  }
  function watch() {
    if (frame || (!pending && !section && !op)) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      const running = appIsBusy();
      const now = performance.now();
      if (pending) {
        const elapsed = now - pending.start;
        const wrapper = marker('.st-key-fm_route_body_' + pending.target);
        const ready = wrapper?.querySelector('[data-setta-aba-pronta="' + pending.target + '"]');
        if (elapsed > 170) root.dataset.settaNavPlaceholder = 'true';
        if (stable(pending, renderedRoute() === pending.target && !running && live(ready)
                         && !wrapper.querySelector(staleSelector))) {
          finishRoute();
        } else if (elapsed > 25_000 ||
          marker('[data-testid="stApp"]')?.dataset.testScriptState === 'compilationError') {
          finishRoute();
        }
      }
      if (section) {
        const elapsed = now - section.start;
        const ready = marker('[data-setta-section-ready="' + section.name + '"]');
        const panel = marker('.st-key-fm_section_panel_' + section.name);
        if (running || (panel && (!live(panel) || panel.querySelector(staleSelector)))) section.started = true;
        const changed = ready?.dataset.settaSectionChoice !== section.previous;
        if (stable(section, !running && live(ready) && panel
                       && !panel.querySelector(staleSelector) && (changed || section.started))
            || elapsed > 25_000 || (!running && !section.started && elapsed > 650)) finishSection();
      }
      if (op) {
        const elapsed = now - op.start;
        const ready = marker('[data-setta-op-pronta]');
        const list = marker('.st-key-fm_issue_ops');
        const complete = !running && live(ready) && ready.dataset.settaOpPronta === op.target
          && list && !list.querySelector(staleSelector);
        if (stable(op, complete)) finishOp(true);
        else if (elapsed > 12_000) finishOp(false);
      }
      watch();
    });
  }
  function startSection(event) {
    if (pending || !(event.target instanceof Element)) return;
    const match = sectionKeys.find(([, selector]) => event.target.closest(selector));
    if (!match) return;
    const picker = event.target.closest(match[1]);
    if (event.type === 'change' && !event.target.matches('input[type="radio"]')) return;
    if (event.type === 'click') {
      // Native/React Aria radios signal real changes themselves. A click on
      // the already active option must not cover the panel for 650 ms.
      if (picker.querySelector('input[type="radio"]')) return;
      const option = event.target.closest('button,[role="radio"]');
      if (!option || option.disabled || option.getAttribute('aria-checked') === 'true'
          || option.getAttribute('aria-pressed') === 'true') return;
    }
    const [name] = match;
    const ready = marker('[data-setta-section-ready="' + name + '"]');
    if (!ready) return;
    section = {name, previous: ready.dataset.settaSectionChoice, start: performance.now()};
    root.dataset.settaSectionLoading = name;
    watch();
  }

  listen('click', event => {
    if (!(event.target instanceof Element)) return;
    if (event.target.closest(toggleSelector)) {
      setDrawer(!drawerOpen());
      return;
    }
    const opButton = event.target.closest('[class*="st-key-fm_issue_select_"] button');
    if (!pending && opButton && !opButton.disabled) {
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
    startSection(event);
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
    finishSection();
    finishOp(false);
    pending = { target, start: performance.now() };
    root.dataset.settaInventoryNavigating = 'true';
    delete root.dataset.settaNavPlaceholder;
    document.querySelector('[data-testid="stMain"]')?.scrollTo({top: 0, behavior: 'instant'});
    watch();
  }, true);

  listen('change', startSection, true);
  listen('keydown', event => {
    if (event.defaultPrevented || event.key !== 'Escape' || !drawerOpen()) return;
    if (!(event.target instanceof Element) ||
        !event.target.closest(sidebarSelector + ',' + toggleSelector)) return;
    setDrawer(false);
    document.querySelector(toggleSelector)?.focus({preventScroll:true});
  });
})();
