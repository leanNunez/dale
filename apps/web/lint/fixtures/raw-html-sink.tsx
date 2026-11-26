// A deliberate violation of every raw HTML sink the lint config bans, one per marked line.
// lint/html-sinks.test.ts proves each marked line fails; `npm run lint` ignores this folder.
export function RawHtmlSinks({ html, frame }: { html: string; frame: HTMLIFrameElement }) {
  const element = document.createElement("div");
  element.innerHTML = html; // sink: innerHTML
  element.outerHTML = html; // sink: outerHTML
  element["innerHTML"] = html; // sink: computed string key
  element[`outerHTML`] = html; // sink: computed template key
  element.insertAdjacentHTML("beforeend", html); // sink: insertAdjacentHTML
  frame.srcdoc = html; // sink: srcdoc property
  frame.setAttribute("srcdoc", html); // sink: setAttribute srcdoc
  element.setAttribute("innerHTML", html); // sink: setAttribute innerHTML
  frame.setAttributeNS(null, "SRCDOC", html); // sink: setAttributeNS any case
  Reflect.set(element, "innerHTML", html); // sink: Reflect.set
  Object.defineProperty(element, "outerHTML", { value: html }); // sink: Object.defineProperty
  element.setHTMLUnsafe(html); // sink: setHTMLUnsafe
  Document.parseHTMLUnsafe(html); // sink: parseHTMLUnsafe
  new DOMParser().parseFromString(html, "text/html"); // sink: DOMParser
  document.createRange().createContextualFragment(html); // sink: createContextualFragment
  document.write(html); // sink: document.write
  document.writeln(html); // sink: document.writeln
  window.document.write(html); // sink: window.document
  document["write"](html); // sink: computed document key
  const alias = document; // sink: aliased document
  alias.title = html;
  eval(html); // sink: eval
  window.eval(html); // sink: window.eval
  new Function(html); // sink: new Function
  setTimeout("alert(1)"); // sink: string setTimeout
  const props = { dangerouslySetInnerHTML: { __html: html } }; // sink: object prop
  const iframe = <iframe srcDoc={html} />; // sink: JSX srcDoc on an iframe
  const any = <div srcDoc={html} />; // sink: JSX srcDoc on any element
  void [iframe, any];
  return <div dangerouslySetInnerHTML={{ __html: html }} {...props} />; // sink: JSX prop
}
