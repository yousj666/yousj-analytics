/* yousj-analytics tracker — lightweight, cookie-free pageview beacon (<2KB).
 * Usage:
 *   <script async src="https://analytics.example.com/tracker.js" data-site="mysite"></script>
 * Optional attributes:
 *   data-endpoint  full collect URL (default: tracker.js URL with filename swapped to /collect)
 *   data-site      site id stored with every event (default: location.hostname)
 */
(function () {
  var s = document.currentScript;
  if (!s) { var all = document.getElementsByTagName('script'); s = all[all.length - 1]; }
  var site = (s && s.getAttribute('data-site')) || location.hostname;
  var endpoint = s && s.getAttribute('data-endpoint');
  if (!endpoint && s && s.src) endpoint = s.src.replace(/\/[^\/]*$/, '/collect');
  if (!endpoint) endpoint = '/collect';

  function send() {
    var payload = {
      site: site,
      path: location.pathname + location.search,
      referrer: document.referrer || '',
      lang: navigator.language || '',
      screen: (screen.width || 0) + 'x' + (screen.height || 0),
      ts: Date.now()
    };
    var body = JSON.stringify(payload);
    if (navigator.sendBeacon) {
      navigator.sendBeacon(endpoint, new Blob([body], { type: 'text/plain' }));
    } else {
      var x = new XMLHttpRequest();
      x.open('POST', endpoint, true);
      x.setRequestHeader('Content-Type', 'text/plain');
      x.send(body);
    }
  }

  if (document.readyState === 'complete') send();
  else window.addEventListener('load', send);
})();
