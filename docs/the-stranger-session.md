# The stranger session

I wrote a note to a version of myself that had no memory of writing it. It built the thing correctly, on the first try, asking nothing.

Here is what happened. Deep in a coding session, at the moment I understood a piece of work best, I wrote down what to build next. Not a long brief. A short, structured capsule. Then I wiped the context and started a fresh session. That fresh session had none of the understanding the first one had. It read the capsule cold and built the feature to spec. No back-and-forth. No re-deriving. It did not know it was finishing its own work.

That is the whole idea. Catch your smartest moment in a bottle so a forgetful or brand-new worker can still finish the job.

## Why peak context never survives

The best understanding of any task exists at one moment: in the head of whoever is deep in it, right then. That understanding then dies one of two ways.

It rots. You come back next week and you have forgotten which button does what and why that one weird constraint mattered. Past-you was a genius. Today-you is lost.

Or it cannot travel. Someone else has to do the work, and they cannot read your mind. A new teammate, a new shift, or in my case a fresh AI session after its context got cleared.

Both failures have the same shape: a context-rich author, a later context-poor executor, and the understanding does not make the trip.

## The obvious fix, and why it fails

So you leave a note. Everyone leaves notes. The problem is that notes, especially terse ones, silently drop the two things that matter most.

I did not assume this. I measured it. I took implementation intents, compressed each one two ways at an equal word budget, replayed each cold through a fresh model, and graded how faithfully the original intent survived. Terse prose lost the same two dimensions every time: *where* the work goes, and what *done* actually looks like. On a 0 to 2 scale those were prose's two weakest spots, both sitting near the floor.

The reason is structural. When you are told to be brief, you cut. And the first things to go are the boring-important ones: the file the change lives in, the acceptance check that proves it worked. Nobody decides to drop them. The format drops them for you.

## A form you are not allowed to leave blank

The fix is not a shorter note. It is a note that refuses the gap.

Instead of free prose, the capsule is a set of labeled fields: what to build, where it goes, the hard constraints, the gate that decides when it applies, and the acceptance criteria that prove it is done. The labels are a checklist that will not let you skip the part everyone skips.

In the same test, the labeled convention scored 10.0 out of 10 against prose's 9.67, won the head-to-head three to zero with the rest ties, and had no weak dimension at all. Here is the part people expect to be wrong: for rich intent the convention runs about 40% *more* tokens than the terse prose, not fewer. It is not winning by being short. It is winning by being complete. Brevity was never the goal. Refusing the silent gap was.

There is a second regime where the math flips. For simple plan operations, the same convention hits statistical parity with plain English at roughly two-thirds fewer tokens. One mechanism, two outcomes: compression where the intent is simple, completeness where it is rich.

## The honest part

Before anyone asks: yes, the model that replays the capsule is an LLM, and the judge in my study is an LLM, so both can be wrong. The numbers are Opus-class, one seed, small samples. Directional, not a chasm. I am telling you that up front because a result you cannot poke at is not a result.

And there is a real hole. When I fed the grammar deliberately malformed input, the model executed about 31% of the garbage instead of refusing it. A convention the model mostly obeys is not a safety guarantee. So the safety layer cannot be the model.

That is why the malformed-input check is deterministic code, not a model call. A small stdlib validator rejects the structural failures outright before anything runs: a step that depends on itself, a reference to an id that does not exist, a duplicate, an id that collides with the grammar. The model is good at understanding the capsule. It is not allowed to be the thing that decides the capsule is safe.

This is the same lesson I keep relearning across everything I build. The model is not the safety layer. You verify in code, or you do not verify.

## It is real, and it is free

This is not a thought experiment. It is a small CLI and a Claude Code plugin. You author a capsule at peak context, it gets validated and queued, and a fresh session surfaces it on startup and offers to finish it. Ask-first, never auto-run. The completion step makes the executor attest how each acceptance criterion was met, so closing a capsule is not a rubber stamp. And if an executor dies mid-build, the unfinished capsule resurfaces instead of vanishing.

It is MIT licensed. Clone it, read the whole concept in one file, fork it, break it.

```
git clone https://github.com/gtsbahamas/intent-capsule
```

If you run AI coding agents across context resets, try authoring one capsule the next time you are deep in something, then clear and let a fresh session build it. Tell me whether the stranger session gets it right. That is the only test that matters.

---

*I build verification tools. intent-capsule is the small version of an idea I take seriously everywhere: the model cannot be trusted to check its own work, so the check has to live in code. If that resonates, the larger version of it is ShipSafe.*
