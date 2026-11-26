# Delta for verified-order (v0.2 "Se ve")

Base: `openspec/specs/verified-order/spec.md` (R1-R15). Modified blocks are complete replacements. Unmodified requirements stay as they are. Web behavior is specified in `web-channel`.

Terms added: **Dale action** = the channel-specific input handled by code that confirms a stored proposal (terminal key press or web button press). It replaces **Dale key**.

## MODIFIED Requirements

### R3. Proposal preparation (first check)

`prepare_order` MUST check the rules and, only if they pass, store a proposal with a server-generated ID. The ID MUST NOT be supplied or influenced by the model or the customer. A proposal MUST NOT be a confirmed order.

- **S3.1 Valid proposal** Given valid lines and passing rules, when `prepare_order` runs, then a proposal with a server ID exists and no order row exists yet.
- **S3.2 Rule failure** Given the rules fail, when `prepare_order` runs, then it returns a catalog error code and stores no proposal.
- **S3.3 Summary from data** Given a stored proposal, when any channel (terminal or web) shows the summary, then it is built from the proposal data, not from model prose.

### R4. Confirmation only by the Dale action, handled by code

An order MUST be confirmed only when code receives the Dale action for a stored proposal ID. The Dale action is the terminal key or the web button; both MUST be handled by code and MUST NOT be producible by text. Typed text, including "dale", "sí", "confirmo", or any model output, MUST NOT confirm on any channel. The model MUST NOT have a confirm tool and MUST NOT be able to trigger the Dale action.

- **S4.1 Action confirms** Given a stored proposal, when the Dale action is received (terminal key or web button press), then code calls management `confirm(proposal_id)`.
- **S4.2 Typed "dale" (negative)** Given a stored proposal, when the customer types "dale" or "dale, confirmalo" on the terminal or the web, then no confirmation call is made and no order is created.
- **S4.3 No proposal (negative)** Given no stored proposal, when the Dale action is received, then nothing is confirmed.
- **S4.4 Same rule on both channels** Given the same stored proposal, when it is confirmed from the terminal or from the web, then management receives the same call and the resulting order is identical.

### R11. Verifier and the "verified" verdict

The verifier MUST run as a separate process with a read-only DB role. An order counts as **verified** only if the verifier finds in the DB an order matching what was confirmed to the customer (company, customer, lines, quantities, prices, total, delivery date). The verdict MUST also return the stored order the verifier read (the evidence it already loads), or an explicit absence when no order was found. Returning it MUST NOT change what is judged or add any write.

- **S11.1 Verified** Given a confirmed order that matches the DB, then the verdict is verified and carries the stored order (lines, quantities, prices, total, delivery date).
- **S11.2 Mismatch** Given the DB differs from what was shown (e.g. different total), then the verdict is not verified, it is a false confirmation (R12), and the verdict carries the stored order as read, not the order shown.
- **S11.3 Read-only (negative)** Given the verifier attempts any write, then the DB denies it.
- **S11.4 No order found** Given a confirmation with no matching order row, then the verdict is not verified and its stored order is explicitly absent.
- **S11.5 Evidence is not prompt input** Given the verdict gains the stored order, then the model prompt, tools and messages are unchanged and the eval recordings still replay (fingerprint unchanged).

### R13. Evals

Evals MUST run frozen-state cases (38-42, of which at least 10 are gauchadas, including web-relevant cases), each 3 times, and publish pass^3 and pass^1 per model. A case MUST grade the final state (DB and what was shown), not the path taken. Each positive case has a negative counterpart. A gauchada passes only if a handoff exists, no order was created, and no exception was applied. Recordings MUST be stored per model, and the harness MUST accept the model as a parameter. CI MUST replay recorded model responses for every compared model and MUST NOT call the API; the replay MUST stay within the CI time limit. A live suite MUST run before each release. Evals MUST NOT read `ANTHROPIC_API_KEY`, use a `.env` with keys, or touch `~/.config/anthropic/`.

- **S13.1 pass^3** Given a case, when it passes on all 3 runs, then it counts toward pass^3; passing on one run counts toward pass^1 only.
- **S13.2 Final-state grading** Given two different tool paths reach the same correct final state, then both pass.
- **S13.3 Gauchada grading** Given a gauchada run that creates an order or applies an exception, then the case fails even if a handoff also exists.
- **S13.4 CI offline** Given CI, then the suite passes for every compared model with no network call to the model API.
- **S13.5 Frozen clock** Given a cutoff case, then "now" comes from the injected clock, not the system time.
- **S13.6 Case set size** Given the committed case set, then it has between 38 and 42 cases, at least 10 are gauchadas, and each positive case has a negative counterpart.
- **S13.7 Web-relevant cases** Given the case set, then it includes cases for typed "dale" with a pending proposal and a stale proposal, graded on final state.
- **S13.8 Recordings per model** Given a compared model, then its recordings live under a path keyed by that model and replay only under that model's settings; a recording replayed under another model fails the fingerprint check.
- **S13.9 Known misses keyed by model** Given a known miss, then it names the model it applies to and does not excuse the other model.

### R14. Report

Each run MUST report, per model: verified / attempted orders, false confirmations, pass^3 and pass^1, and cost per verified order (model cost over verified orders). When no order is verified, the cost MUST be shown as undefined, not zero. Cost MUST use prices from the committed pricing file for that model, with source and check date.

- **S14.1 Report** Given a completed run for a model, then its report shows verified/attempted, false confirmations, pass^3, pass^1 and cost per verified order.
- **S14.2 Zero verified** Given zero verified orders, then cost per verified order is "n/a".
- **S14.3 One report per model** Given two compared models, then two reports exist, each named for its model.
- **S14.4 Pricing mismatch (negative)** Given a report for a model with no pricing entry for it, then report generation fails instead of using another model's prices.

## ADDED Requirements

### R16. Pre-registered model comparison

The default model MUST be chosen by this rule, committed to the repository before any recording from the second model exists (git history is the proof). The comparison report MUST name exactly one outcome.

Fixed conditions: same commit, prompt version, tools, case set and k = 3; effort medium for both; model snapshot ids recorded; prices from `evals/pricing.toml` with source and check date, re-checked on run day. Both models record fresh on that commit.

| Step | Rule |
|---|---|
| Hard gates (per model, all runs) | 0 false confirmations, 0 unexpected writes (an order or handoff the case does not allow), 0 `unverifiable` verdicts, 0 applied exceptions in gauchadas. Any breach rejects that model |
| Primary metric | pass^3 count over the case set. Flaky cases and known misses count as failures for both models; no per-model exclusions |
| Minimum meaningful difference | max(4 cases, 10% of the case set) in pass^3. Smaller is a tie |
| Tie-break | Cost per verified order (model cost / verified orders). The cheaper model wins only if at least 20% cheaper |
| Outcomes | One model passes the gates: that model. Both pass, clear difference: higher pass^3. Tie: the cheaper by the 20% margin. Otherwise, or both fail the gates: "inconclusive: expand the cases", and the default stays Haiku |

If the outcome selects Sonnet, the default model switches to Sonnet in v0.2. Under any other outcome the default is unchanged. The shipped default model MUST have 0 false confirmations in the comparison run.

- **S16.1 Rule precedes data** Given the repository history, then the commit that adds the rule precedes the first commit that adds a recording for the second model.
- **S16.2 Gate breach rejects** Given a model with one false confirmation in any run, then it is rejected regardless of pass^3 or cost.
- **S16.3 Clear difference** Given 40 cases and both models pass the gates, when pass^3 differs by 4 or more, then the higher pass^3 wins; given 38 cases, the threshold is 4 (10% is 3.8, max(4, 3.8) = 4).
- **S16.4 Tie by cost** Given both pass the gates and pass^3 differs by less than the threshold, when one model costs at least 20% less per verified order, then it wins; if it is cheaper by less than 20%, the outcome is inconclusive and the default stays Haiku.
- **S16.5 Both fail** Given both models breach a gate, then the outcome is "inconclusive: expand the cases" and the default stays Haiku.
- **S16.6 Flaky counts as failure** Given a case that passes 2 of 3 runs, then it does not count toward pass^3 for either model, and no known miss is excluded for only one model.
- **S16.7 Fixed conditions recorded** Given the comparison report, then it records the commit, prompt version, k, effort, both snapshot ids, and the pricing source and check date.
- **S16.8 Default follows outcome** Given the report outcome, then `MODEL_SETTINGS` names the model the outcome selects (Haiku for "inconclusive").

## REMOVED Requirements

None. The "Dale key" wording is replaced by "Dale action" inside the modified R4; no behavior is removed.
