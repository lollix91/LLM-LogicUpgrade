%% ============================================================
%% DALI2 Logic Solver Agent
%% Purpose: Receives logical facts, rules, and queries from the
%%          orchestrator and solves them using Prolog inference.
%%
%% DALI2 execution model:
%%   - Helpers are called via helper(name(Args)) in bodies
%%   - Actions are called via do(name(Args)) in bodies
%%   - Built-in DSL: assert_belief, retract_belief, believes, log, send
%%   - Arithmetic/comparison: is, >, <, =, \=, ==, etc.
%%   - Multiple helper clauses: pattern-matched (first unifying wins)
%%     so clauses with SAME pattern need if-then-else in single body
%% ============================================================

:- agent(logic_solver, [cycle(1)]).

%% --- Reactive Rules ---

%% Main entry point: receive a solve_logic event from the orchestrator
%% containing facts, rules, and a query to solve.
solve_logicE(Facts, Rules, Query) :>
    log("=== LOGIC SOLVER: Received problem ==="),
    log("Facts: ~w", [Facts]),
    log("Rules: ~w", [Rules]),
    log("Query: ~w", [Query]),
    helper(clear_state),
    do(solve(Facts, Rules, Query)).

%% Clear all stale beliefs before a new solve.
%% Uses retractall/1 directly on the local Prolog DB to guarantee ALL
%% matching beliefs are removed atomically — bypassing the believes/retract_belief
%% DSL layer, which only removes one belief per call and may not see
%% in-flight retractions within the same action cycle.
helper(clear_state) :-
    retractall(agent_belief_rt(solution(_))),
    retractall(agent_belief_rt(result_binding(_))),
    retractall(agent_belief_rt(logic_explanation(_))),
    retractall(agent_belief_rt(kb_fact(_))),
    retractall(agent_belief_rt(kb_rule(_))).

%% --- Action: Solve the logical problem ---

solveA(Facts, Rules, Query) :-
    log("Asserting knowledge base..."),
    helper(assert_facts(Facts)),
    helper(assert_rules(Rules)),
    log("Evaluating query: ~w", [Query]),
    helper(evaluate_query(Query)).

%% --- Helpers ---

%% Assert all facts into the belief base
helper(assert_facts([])) :- true.
helper(assert_facts([Fact|Rest])) :-
    assert_belief(kb_fact(Fact)),
    helper(assert_facts(Rest)).

%% Assert rules as belief entries
helper(assert_rules([])) :- true.
helper(assert_rules([Rule|Rest])) :-
    assert_belief(kb_rule(Rule)),
    helper(assert_rules(Rest)).

%% Evaluate query: commit to the FIRST solution (which binds query
%% variables), then store it. Backtracking happens INSIDE solve/2 to
%% explore all facts and rules; the if-then here just takes one answer.
%% Depth limit of 20 prevents exponential blowup from malformed rules.
helper(evaluate_query(Query)) :-
    ( helper(solve(Query, 20)) ->
        log("=== SOLUTION FOUND: ~w ===", [Query]),
        assert_belief(solution(Query)),
        log("Logic solving complete.")
    ;
        log("=== NO SOLUTION (query failed) ==="),
        assert_belief(solution(no_solution)),
        assert_belief(logic_explanation(query_failed))
    ).

%% ============================================================
%% Core meta-interpreter: solve(Goal, Depth)
%%
%% Extended SLD resolution with depth limit. Supports:
%% - Conjunction (A, B)
%% - Disjunction (A ; B)
%% - Negation-as-failure: not(G) and \+(G)
%% - Arithmetic: is/2, >/2, </2, >=/2, =</2, =:=/2, =\=/2
%% - Unification: =/2, \=/2, ==/2, \==/2
%% - If-then-else: (Cond -> Then ; Else)
%% - Findall: findall(T, G, Bag)
%% - Forall: forall(Cond, Action)
%% - List operations: member/2, length/2, append/3, nth0/3, nth1/3
%%   msort/2, sort/2, last/2, sumlist/2, max_list/2, min_list/2
%% - Cut-like: once(G)
%%
%% IMPORTANT (DALI2 execution model): the engine's helper(...) dispatch
%% commits to the FIRST helper clause whose head unifies, but the chosen
%% clause body still backtracks fully. Therefore the clauses below have
%% mutually-exclusive head patterns, and the atomic clause uses a
%% DISJUNCTION so backtracking explores every matching fact AND rule.
%% ============================================================

%% --- Base cases ---
helper(solve(true, _)) :- true.
helper(solve(fail, _)) :- fail.

%% --- Conjunction ---
helper(solve((A, B), D)) :-
    helper(solve(A, D)),
    helper(solve(B, D)).

%% --- Disjunction ---
helper(solve((A ; B), D)) :-
    ( helper(solve(A, D))
    ; helper(solve(B, D))
    ).

%% --- If-then-else: (Cond -> Then ; Else) ---
helper(solve((Cond -> Then ; Else), D)) :-
    ( helper(solve(Cond, D)) ->
        helper(solve(Then, D))
    ;
        helper(solve(Else, D))
    ).

%% --- If-then (no else): (Cond -> Then) ---
helper(solve((Cond -> Then), D)) :-
    helper(solve(Cond, D)),
    helper(solve(Then, D)).

%% --- Negation-as-failure ---
helper(solve(not(G), D)) :-
    not(helper(solve(G, D))).

helper(solve(\+(G), D)) :-
    \+(helper(solve(G, D))).

%% --- Arithmetic evaluation ---
helper(solve((X is Expr), _)) :-
    X is Expr.

%% --- Arithmetic comparison ---
helper(solve((X > Y), _)) :- X > Y.
helper(solve((X < Y), _)) :- X < Y.
helper(solve((X >= Y), _)) :- X >= Y.
helper(solve((X =< Y), _)) :- X =< Y.
helper(solve((X =:= Y), _)) :- X =:= Y.
helper(solve((X =\= Y), _)) :- X =\= Y.

%% --- Unification ---
helper(solve((X = Y), _)) :- X = Y.
helper(solve((X \= Y), _)) :- X \= Y.
helper(solve((X == Y), _)) :- X == Y.
helper(solve((X \== Y), _)) :- X \== Y.

%% --- Findall ---
helper(solve(findall(Template, Goal, Bag), D)) :-
    findall(Template, helper(solve(Goal, D)), Bag).

%% --- Forall ---
helper(solve(forall(Cond, Action), D)) :-
    forall(helper(solve(Cond, D)), helper(solve(Action, D))).

%% --- Once (first solution only) ---
helper(solve(once(G), D)) :-
    once(helper(solve(G, D))).

%% --- List operations (delegated to SWI-Prolog builtins) ---
helper(solve(member(X, L), _)) :- member(X, L).
helper(solve(length(L, N), _)) :- length(L, N).
helper(solve(append(A, B, C), _)) :- append(A, B, C).
helper(solve(nth0(I, L, E), _)) :- nth0(I, L, E).
helper(solve(nth1(I, L, E), _)) :- nth1(I, L, E).
helper(solve(last(L, E), _)) :- last(L, E).
helper(solve(msort(L, S), _)) :- msort(L, S).
helper(solve(sort(L, S), _)) :- sort(L, S).
helper(solve(sumlist(L, S), _)) :- sumlist(L, S).
helper(solve(max_list(L, M), _)) :- max_list(L, M).
helper(solve(min_list(L, M), _)) :- min_list(L, M).

%% --- Integer enumeration (for generate-and-test) ---
helper(solve(between(L, H, X), _)) :- between(L, H, X).
helper(solve(succ(X, Y), _)) :- succ(X, Y).
helper(solve(plus(X, Y, Z), _)) :- plus(X, Y, Z).
helper(solve(abs(X, Y), _)) :- Y is abs(X).

%% --- Type checks ---
helper(solve(number(X), _)) :- number(X).
helper(solve(atom(X), _)) :- atom(X).
helper(solve(integer(X), _)) :- integer(X).
helper(solve(var(X), _)) :- var(X).
helper(solve(nonvar(X), _)) :- nonvar(X).
helper(solve(ground(X), _)) :- ground(X).

%% --- Atomic goal: resolve against KB facts and rules ---
helper(solve(Goal, D)) :-
    Goal \= true,
    Goal \= fail,
    Goal \= (_, _),
    Goal \= (_ ; _),
    Goal \= (_ -> _ ; _),
    Goal \= (_ -> _),
    Goal \= not(_),
    Goal \= \+(_),
    Goal \= (_ is _),
    Goal \= (_ > _),
    Goal \= (_ < _),
    Goal \= (_ >= _),
    Goal \= (_ =< _),
    Goal \= (_ =:= _),
    Goal \= (_ =\= _),
    Goal \= (_ = _),
    Goal \= (_ \= _),
    Goal \= (_ == _),
    Goal \= (_ \== _),
    Goal \= findall(_, _, _),
    Goal \= forall(_, _),
    Goal \= once(_),
    Goal \= member(_, _),
    Goal \= length(_, _),
    Goal \= append(_, _, _),
    Goal \= nth0(_, _, _),
    Goal \= nth1(_, _, _),
    Goal \= last(_, _),
    Goal \= msort(_, _),
    Goal \= sort(_, _),
    Goal \= sumlist(_, _),
    Goal \= max_list(_, _),
    Goal \= min_list(_, _),
    Goal \= number(_),
    Goal \= atom(_),
    Goal \= integer(_),
    Goal \= var(_),
    Goal \= nonvar(_),
    Goal \= ground(_),
    Goal \= between(_, _, _),
    Goal \= succ(_, _),
    Goal \= plus(_, _, _),
    Goal \= abs(_, _),
    D > 0,
    D1 is D - 1,
    ( believes(kb_fact(Goal))
    ; believes(kb_rule((Goal :- Body))),
      helper(solve(Body, D1))
    ).

%% --- Simple query event (for direct testing) ---
queryE(Q) :>
    log("Direct query: ~w", [Q]),
    helper(evaluate_query(Q)).

%% --- Told rules: accept all messages from orchestrator ---
told(_, solve_logic(_, _, _), 100) :- true.
told(_, query(_), 50) :- true.
told(_, reset, 10) :- true.

%% --- Reset event ---
resetE :>
    log("Resetting logic solver state"),
    retract_belief(solution(_)),
    retract_belief(result_binding(_)),
    retract_belief(logic_explanation(_)),
    retract_belief(kb_fact(_)),
    retract_belief(kb_rule(_)).

%% --- Initial beliefs ---
believes(status(ready)).
