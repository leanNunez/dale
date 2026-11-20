/**
 * The page renders model-controlled text, so raw HTML and string-to-code sinks are banned
 * outright (W10, S10.3). The rule is a name ban, not a usage analysis: a sink's name may not
 * appear in the page's source at all, as an identifier, a JSX attribute, a property key or a
 * string (any case, so `setAttribute("SRCDOC")` fails too). That one ban covers member access,
 * computed access (`el["innerHTML"]`, `` el[`srcdoc`] ``), `setAttribute`, `Reflect.set`,
 * `Object.defineProperty`, object and spread props and `createElement`. `document` may only be
 * read as `document.<name>`, never aliased, passed on or reached through `window`, so
 * `document.write` cannot hide behind another name. A key built at run time cannot be checked
 * statically; the CSP of ADR 0005 (no inline script) is the second line.
 */
const SINKS = [
  "innerHTML",
  "outerHTML",
  "insertAdjacentHTML",
  "dangerouslySetInnerHTML",
  "srcdoc",
  "setHTMLUnsafe",
  "parseHTMLUnsafe",
  "createContextualFragment",
  "DOMParser",
  "parseFromString",
];
const NAME = `/^(${SINKS.join("|")})$/i`;
const DOCUMENT_KEY = "/^(document|write|writeln)$/";
const DOCUMENT_ONLY_AS_OBJECT =
  "Identifier[name='document']:not(MemberExpression[computed=false] > Identifier.object)";
const COMPUTED_DOCUMENT_KEY =
  `MemberExpression[computed=true] > :matches(Literal[value=${DOCUMENT_KEY}], ` +
  `TemplateLiteral[quasis.0.value.cooked=${DOCUMENT_KEY}]).property`;
const MESSAGE = "Raw HTML sinks are banned: render model text as a React text node.";

export const htmlSinkRules = {
  "react/no-danger": "error",
  "no-restricted-syntax": [
    "error",
    { selector: `:matches(Identifier, JSXIdentifier)[name=${NAME}]`, message: MESSAGE },
    { selector: `Literal[value=${NAME}]`, message: MESSAGE },
    { selector: `TemplateElement[value.cooked=${NAME}]`, message: MESSAGE },
    {
      selector: DOCUMENT_ONLY_AS_OBJECT,
      message: "Use `document` only as `document.<name>`, so a write cannot hide behind an alias.",
    },
    {
      selector: "MemberExpression[object.name='document'][property.name=/^(write|writeln)$/]",
      message: "document.write is banned: render model text as a React text node.",
    },
    {
      selector: COMPUTED_DOCUMENT_KEY,
      message: "document.write is banned: render model text as a React text node.",
    },
  ],
  // eval, window.eval, new Function, Function(...) and a string passed to setTimeout/setInterval.
  "no-eval": "error",
  "no-implied-eval": "error",
  "no-new-func": "error",
};
