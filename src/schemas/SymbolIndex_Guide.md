# SymbolIndex Reference Guide

## Purpose

SymbolIndex is a side-index used to resolve case-insensitive, ambiguous, or overloaded symbol names coming from LLM-driven queries into exact Neo4j graph node identities. It preserves the case-sensitive semantics of the code graph while allowing flexible querying.

---

## Why scope can be empty

The scope property represents the enclosing context of a symbol.

An empty scope means the symbol is defined at the top level:
- No enclosing namespace
- No enclosing type

This is valid and expected for global or file-level symbols.

---

## SymbolIndex Node

Label:
SymbolIndex

This node is not part of the code structure graph. It exists only for symbol resolution.

---

## Properties

Common properties for all symbols:

- key_lc: lowercase symbol name
- kind: Type, Function, Variable, Namespace, Macro
- scope: enclosing namespace, type name, or empty string
- targets: list of Neo4j internal node ids

Function-only properties:

- arity: number of parameters
- signature_lc: lowercase canonical parameter signature

---

## Symbol Identity Rules

A symbol is uniquely identified by:
- key_lc
- kind
- scope
- arity and signature_lc for functions

---

## Constraints

Create these constraints before backfilling.

```bash
CREATE CONSTRAINT symbol_index_type
IF NOT EXISTS
FOR (s:SymbolIndex)
REQUIRE (s.key_lc, s.kind, s.scope) IS UNIQUE;
```
```bash
CREATE CONSTRAINT symbol_index_function
IF NOT EXISTS
FOR (s:SymbolIndex)
REQUIRE (s.key_lc, s.kind, s.scope, s.arity, s.signature_lc) IS UNIQUE;
```
```bash
CREATE CONSTRAINT symbol_index_variable
IF NOT EXISTS
FOR (s:SymbolIndex)
REQUIRE (s.key_lc, s.kind, s.scope) IS UNIQUE;
```
```bash
CREATE CONSTRAINT symbol_index_namespace
IF NOT EXISTS
FOR (s:SymbolIndex)
REQUIRE (s.key_lc, s.kind, s.scope) IS UNIQUE;
```
---

## Backfill Queries

Type symbols:
```bash
MATCH (t:Type)
OPTIONAL MATCH (t)<-[:CONTAINS]-(ns:Namespace)
WITH toLower(t.name) AS key_lc,
     coalesce(ns.path, "") AS scope,
     id(t) AS tid
MERGE (s:SymbolIndex { key_lc: key_lc, kind: "Type", scope: scope })
SET s.targets =
  CASE
    WHEN s.targets IS NULL THEN [tid]
    WHEN NOT tid IN s.targets THEN s.targets + tid
    ELSE s.targets
  END;
```
Function symbols:
```bash
MATCH (f:Function)
OPTIONAL MATCH (f)<-[:CONTAINS]-(t:Type)
OPTIONAL MATCH (f)<-[:CONTAINS]-(ns:Namespace)
WITH toLower(f.name) AS key_lc,
     coalesce(t.name, ns.path, "") AS scope,
     size(
       CASE
         WHEN f.parameters IS NULL OR trim(f.parameters) = "" THEN []
         ELSE split(f.parameters, ",")
       END
     ) AS arity,
     toLower(replace(coalesce(f.parameters, ""), " ", "")) AS signature_lc,
     id(f) AS fid
MERGE (s:SymbolIndex {
  key_lc: key_lc,
  kind: "Function",
  scope: scope,
  arity: arity,
  signature_lc: signature_lc})
SET s.targets =
  CASE
    WHEN s.targets IS NULL THEN [fid]
    WHEN NOT fid IN s.targets THEN s.targets + fid
    ELSE s.targets
  END;
```
Variable symbols:
```bash
MATCH (v:Variable)
OPTIONAL MATCH (v)<-[:DECLARES]-(owner)
WITH toLower(v.name) AS key_lc,
     coalesce(toString(id(owner)), "") AS scope,
     id(v) AS vid
MERGE (s:SymbolIndex { key_lc: key_lc, kind: "Variable", scope: scope })
SET s.targets =
  CASE
    WHEN s.targets IS NULL THEN [vid]
    WHEN NOT vid IN s.targets THEN s.targets + vid
    ELSE s.targets
  END;
```
Namespace symbols:
```bash
MATCH (n:Namespace)
WITH toLower(n.name) AS key_lc,
     coalesce(n.path, "") AS scope,
     id(n) AS nid
MERGE (s:SymbolIndex { key_lc: key_lc, kind: "Namespace", scope: scope })
SET s.targets =
  CASE
    WHEN s.targets IS NULL THEN [nid]
    WHEN NOT nid IN s.targets THEN s.targets + nid
    ELSE s.targets
  END;
```
Macro symbols:
```bash
MATCH (m:Macro)
WITH toLower(m.name) AS key_lc,
     coalesce(m.file_path, "") AS scope,
     id(m) AS mid
MERGE (s:SymbolIndex { key_lc: key_lc, kind: "Macro", scope: scope })
SET s.targets =
  CASE
    WHEN s.targets IS NULL THEN [mid]
    WHEN NOT mid IN s.targets THEN s.targets + mid
    ELSE s.targets
  END;
```
---

## Query Time Rules

- Always resolve symbols via SymbolIndex first
- Use node ids for execution queries
- Avoid TOLOWER, CONTAINS, or regex in execution Cypher
- Zero execution results indicate resolution failure

---

## Mental Model

LLM suggests.
Resolver decides.
Graph executes.
