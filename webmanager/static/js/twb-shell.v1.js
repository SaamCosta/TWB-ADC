(function () {
  'use strict';

  var shell = document.querySelector('.twb-shell');
  var toggle = document.querySelector('[data-nav-toggle]');
  var backdrop = document.querySelector('[data-nav-dismiss]');

  function setNav(open) {
    if (!shell || !toggle) return;
    shell.setAttribute('data-nav-open', open ? 'true' : 'false');
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) {
      var firstLink = document.querySelector('.twb-sidebar a');
      if (firstLink) firstLink.focus();
    } else {
      toggle.focus();
    }
  }

  if (toggle) toggle.addEventListener('click', function () {
    setNav(shell.getAttribute('data-nav-open') !== 'true');
  });
  if (backdrop) backdrop.addEventListener('click', function () { setNav(false); });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && shell && shell.getAttribute('data-nav-open') === 'true') setNav(false);
  });

  function formatAge(seconds) {
    if (seconds < 60) return 'agora';
    if (seconds < 3600) return 'há ' + Math.floor(seconds / 60) + ' min';
    if (seconds < 86400) return 'há ' + Math.floor(seconds / 3600) + ' h';
    return 'há ' + Math.floor(seconds / 86400) + ' d';
  }

  document.querySelectorAll('[data-observed-at]').forEach(function (element) {
    var timestamp = Number(element.getAttribute('data-observed-at'));
    if (!timestamp) return;
    var age = Math.max(0, Math.floor(Date.now() / 1000 - timestamp));
    element.textContent = formatAge(age);
    element.setAttribute('title', new Date(timestamp * 1000).toLocaleString('pt-BR') + ' · sem SLA de frescor definido');
  });

  document.querySelectorAll('[data-copy-coordinate]').forEach(function (button) {
    button.addEventListener('click', function () {
      var value = button.getAttribute('data-copy-coordinate');
      if (!value || !navigator.clipboard) return;
      navigator.clipboard.writeText(value).then(function () {
        var previous = button.textContent;
        button.textContent = 'Copiado';
        setTimeout(function () { button.textContent = previous; }, 1400);
      });
    });
  });
})();
