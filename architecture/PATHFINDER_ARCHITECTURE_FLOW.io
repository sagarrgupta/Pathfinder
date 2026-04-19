<mxfile host="app.diagrams.net" agent="Pathfinder">
  <diagram name="Pathfinder Query Flow" id="pathfinder-query-flow">
    <mxGraphModel dx="1006" dy="694" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="0" pageScale="1" pageWidth="1400" pageHeight="2000" math="0" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        <mxCell id="title" parent="1" style="text;html=1;align=center;verticalAlign=middle;fontSize=20;fontStyle=1;strokeColor=none;fillColor=none;" value="Pathfinder — End-to-End Query Flow" vertex="1">
          <mxGeometry height="32" width="420" x="330" y="14" as="geometry" />
        </mxCell>
        <mxCell id="react" parent="1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;fontSize=11;arcSize=8;align=center;fontColor=#1a2a3a;" value="&lt;b&gt;React / Vite Frontend&lt;/b&gt;&lt;br&gt;ChatPage · InputArea · StreamingProgress&lt;br&gt;&lt;font color=&quot;#5a6a7a&quot;&gt;Vite dev server · port 5173&lt;/font&gt;" vertex="1">
          <mxGeometry height="72" width="310" x="385" y="58" as="geometry" />
        </mxCell>
        <mxCell id="fastapi" parent="1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#e1d5e7;strokeColor=#9673a6;fontSize=10;arcSize=8;align=left;" value="&lt;b&gt;FastAPI  ·  POST /api/v1/chat&lt;/b&gt;&lt;br&gt;① Resolve / create student node&lt;br&gt;② Delete replaced documents from Neo4j&lt;br&gt;③ Validate &amp;amp; read uploaded files&lt;br&gt;④ Compile LangGraph (SQLite checkpointer)&lt;br&gt;⑤ Build initial PathfinderState&lt;br&gt;&lt;font color=&quot;#5a3a6a&quot;&gt;Uvicorn · port 8001 · Returns SSE stream&lt;/font&gt;" vertex="1">
          <mxGeometry height="115" width="310" x="385" y="205" as="geometry" />
        </mxCell>
        <mxCell id="lg_container" parent="1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f0fff0;strokeColor=#52be80;strokeWidth=3;dashed=0;fontSize=10;fontStyle=1;verticalAlign=top;align=center;" value="LangGraph  StateGraph  ·  SQLite checkpointer  ·  thread_id = student_id : session_id" vertex="1">
          <mxGeometry height="1405" width="742" x="168" y="395" as="geometry" />
        </mxCell>
        <mxCell id="n1_guard" parent="1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=10;arcSize=8;align=center;" value="&lt;b&gt;① Input Guard&lt;/b&gt;&lt;br&gt;Check: empty query · length &amp;gt; 4000 chars · 9 injection regex patterns&lt;br&gt;&lt;font color=&quot;#3a6a3a&quot;&gt;app/nodes/input_guard.py&lt;/font&gt;" vertex="1">
          <mxGeometry height="62" width="310" x="385" y="438" as="geometry" />
        </mxCell>
        <mxCell id="d1_blocked" parent="1" style="rhombus;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;fontSize=11;fontStyle=1;align=center;" value="Blocked?" vertex="1">
          <mxGeometry height="60" width="168" x="455" y="550" as="geometry" />
        </mxCell>
        <mxCell id="blocked_box" parent="1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;fontSize=9;align=center;" value="&lt;b&gt;BLOCKED&lt;/b&gt;&lt;br&gt;Skip all LLM &amp;amp; tools&lt;br&gt;→ directly to Responder" vertex="1">
          <mxGeometry height="55" width="150" x="40" y="580" as="geometry" />
        </mxCell>
        <mxCell id="n2_orch" parent="1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=10;arcSize=8;align=center;" value="&lt;b&gt;② Orchestrator&lt;/b&gt;&lt;br&gt;Fetch student profile · LLM scores specialists (0–10)&lt;br&gt;Select: academic · career · general&lt;br&gt;Fallback to general if LLM fails&lt;br&gt;&lt;font color=&quot;#3a6a3a&quot;&gt;app/nodes/orchestrator.py&lt;/font&gt;" vertex="1">
          <mxGeometry height="88" width="310" x="385" y="670" as="geometry" />
        </mxCell>
        <mxCell id="n3_container" parent="1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#fffde7;strokeColor=#d6b656;strokeWidth=2;dashed=1;fontSize=10;fontStyle=1;verticalAlign=top;align=center;" value="③ Specialist Runner  ·  app/nodes/specialist_runner.py" vertex="1">
          <mxGeometry height="561" width="575" x="265" y="810" as="geometry" />
        </mxCell>
        <mxCell id="n3_ctx_note" parent="1" style="text;html=1;align=left;verticalAlign=middle;fontSize=9;strokeColor=none;fillColor=#fffde7;fontStyle=2;" value="Context assembled before LLM call:  student_schema · student profile · session_context · long_context (Neo4j) · last 10 messages" vertex="1">
          <mxGeometry height="20" width="548" x="278" y="844" as="geometry" />
        </mxCell>
        <mxCell id="d2_files" parent="1" style="rhombus;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;fontSize=10;fontStyle=1;align=center;" value="Files?" vertex="1">
          <mxGeometry height="60" width="124" x="477" y="864" as="geometry" />
        </mxCell>
        <mxCell id="n3_da" parent="1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#ffe6cc;strokeColor=#d79b00;fontSize=9;arcSize=6;align=left;" value="&lt;b&gt;Doc Analyst (sub-step)&lt;/b&gt;&lt;br&gt;① Extract text&lt;br&gt;   PDF→PyMuPDF · DOCX→python-docx&lt;br&gt;   Image→Vision LLM (LM Studio)&lt;br&gt;② Chunk  (700 chars / 120 overlap)&lt;br&gt;③ Embed → Ollama mxbai-embed-large&lt;br&gt;④ Store chunks → Neo4j vector index&lt;br&gt;⑤ LLM-guided graph ingestion&lt;br&gt;   (sections · entities · relations · fields)&lt;br&gt;&lt;font color=&quot;#7a3e00&quot;&gt;app/nodes/doc_analyst.py&lt;/font&gt;" vertex="1">
          <mxGeometry height="165" width="230" x="275" y="986" as="geometry" />
        </mxCell>
        <mxCell id="n3_loop" parent="1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#fff9c4;strokeColor=#d6b656;fontSize=9;arcSize=5;align=left;" value="&lt;b&gt;Agentic Tool-Use Loop&lt;/b&gt;  (≤ 12 iterations)&lt;br&gt;&lt;br&gt;LLM call (LM Studio) with bound tools&lt;br&gt;│&lt;br&gt;├─ tool_call? → execute_tool() → ToolMessage&lt;br&gt;│&lt;br&gt;│   Graph: get_student_schema · typed_node_lookup&lt;br&gt;│          hybrid_search · upsert_graph_node · bfs_neighbors&lt;br&gt;│&lt;br&gt;│   Vector: hybrid_search · get_chunks_for_document&lt;br&gt;│&lt;br&gt;│   Web: search_web → fetch_url&lt;br&gt;│         find_official_sources&lt;br&gt;│&lt;br&gt;└─ respond() called → capture specialist_output&lt;br&gt;&lt;br&gt;Safety net: &lt;i&gt;&quot;couldn&#39;t find&quot; + &lt; 2 searches → retry once&lt;/i&gt;" vertex="1">
          <mxGeometry height="340" width="290" x="536" y="950" as="geometry" />
        </mxCell>
        <mxCell id="n4_validator" parent="1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=10;arcSize=8;align=center;" value="&lt;b&gt;④ Response Validator&lt;/b&gt;&lt;br&gt;Validate message · Extract citations from tool_call_log (URLs / titles)&lt;br&gt;&lt;font color=&quot;#3a6a3a&quot;&gt;app/nodes/response_validator.py&lt;/font&gt;" vertex="1">
          <mxGeometry height="62" width="310" x="385" y="1440" as="geometry" />
        </mxCell>
        <mxCell id="n5_persister" parent="1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=10;arcSize=8;align=center;" value="&lt;b&gt;⑤ Context Persister&lt;/b&gt;&lt;br&gt;Write next_session_context → state&lt;br&gt;Write next_long_context → Neo4j Student node (persists across sessions)&lt;br&gt;&lt;font color=&quot;#3a6a3a&quot;&gt;app/nodes/context_persister.py&lt;/font&gt;" vertex="1">
          <mxGeometry height="72" width="310" x="385" y="1562" as="geometry" />
        </mxCell>
        <mxCell id="n6_responder" parent="1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=10;arcSize=8;align=center;" value="&lt;b&gt;⑥ Responder&lt;/b&gt;&lt;br&gt;Package final_answer · Append AIMessage → LangGraph history (SQLite)&lt;br&gt;&lt;font color=&quot;#3a6a3a&quot;&gt;app/nodes/responder.py&lt;/font&gt;" vertex="1">
          <mxGeometry height="60" width="310" x="385" y="1694" as="geometry" />
        </mxCell>
        <mxCell id="sse_response" parent="1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;fontSize=10;arcSize=8;align=left;" value="&lt;b&gt;SSE Stream  →  React Frontend&lt;/b&gt;&lt;br&gt;① &lt;i&gt;progress&lt;/i&gt; events — one per node (status / stage label)&lt;br&gt;② &lt;i&gt;token&lt;/i&gt; events — final_answer in 120-char chunks&lt;br&gt;③ &lt;i&gt;done&lt;/i&gt; event — citations · replay_id · tool_call_log · routing_scores · dependency_status" vertex="1">
          <mxGeometry height="80" width="370" x="355" y="1836" as="geometry" />
        </mxCell>
        <mxCell id="replay_note" parent="1" style="text;html=1;align=center;verticalAlign=middle;fontSize=9;strokeColor=none;fillColor=none;fontStyle=2;" value="Replay artifact (full turn snapshot) saved to data/replays/ before done event is sent" vertex="1">
          <mxGeometry height="18" width="370" x="355" y="1924" as="geometry" />
        </mxCell>
        <mxCell id="lmstudio_svc" parent="1" style="shape=cylinder3;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;fontSize=9;boundedLbl=1;backgroundOutline=1;size=8;align=center;" value="&lt;b&gt;LM Studio&lt;/b&gt;&lt;br&gt;Text + Vision LLM&lt;br&gt;google/gemma-4-26b&lt;br&gt;&lt;font color=&quot;#5a6a7a&quot;&gt;localhost:1234/v1&lt;/font&gt;" vertex="1">
          <mxGeometry height="80" width="168" x="1010" y="690" as="geometry" />
        </mxCell>
        <mxCell id="neo4j_svc" parent="1" style="shape=cylinder3;whiteSpace=wrap;html=1;fillColor=#e1d5e7;strokeColor=#9673a6;fontSize=9;boundedLbl=1;backgroundOutline=1;size=8;align=center;" value="&lt;b&gt;Neo4j&lt;/b&gt;&lt;br&gt;Knowledge Graph&lt;br&gt;+ Vector Index&lt;br&gt;&lt;font color=&quot;#5a6a7a&quot;&gt;bolt://localhost:7687&lt;/font&gt;" vertex="1">
          <mxGeometry height="80" width="168" x="1010" y="880" as="geometry" />
        </mxCell>
        <mxCell id="ollama_svc" parent="1" style="shape=cylinder3;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=9;boundedLbl=1;backgroundOutline=1;size=8;align=center;" value="&lt;b&gt;Ollama&lt;/b&gt;&lt;br&gt;mxbai-embed-large&lt;br&gt;1024-dim embeddings&lt;br&gt;&lt;font color=&quot;#5a6a7a&quot;&gt;localhost:11434&lt;/font&gt;" vertex="1">
          <mxGeometry height="80" width="168" x="1010" y="1005" as="geometry" />
        </mxCell>
        <mxCell id="web_search_svc" parent="1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#ffe6cc;strokeColor=#d79b00;fontSize=9;align=center;" value="&lt;b&gt;Web Search&lt;/b&gt;&lt;br&gt;Tavily → Google CSE&lt;br&gt;→ Brave → DuckDuckGo&lt;br&gt;&lt;font color=&quot;#5a6a7a&quot;&gt;(fallback chain)&lt;/font&gt;" vertex="1">
          <mxGeometry height="72" width="168" x="1010" y="1110" as="geometry" />
        </mxCell>
        <mxCell id="sqlite_svc" parent="1" style="shape=cylinder3;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#808080;fontSize=9;boundedLbl=1;backgroundOutline=1;size=8;align=center;" value="&lt;b&gt;SQLite&lt;/b&gt;&lt;br&gt;LangGraph Checkpointer&lt;br&gt;Conversation history&lt;br&gt;&lt;font color=&quot;#5a6a7a&quot;&gt;data/pathfinder.db&lt;/font&gt;" vertex="1">
          <mxGeometry height="80" width="168" x="1010" y="1562" as="geometry" />
        </mxCell>
        <mxCell id="legend_bg" parent="1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#fafafa;strokeColor=#bbb;fontSize=9;" value="" vertex="1">
          <mxGeometry height="185" width="110" x="40" y="376.5" as="geometry" />
        </mxCell>
        <mxCell id="legend_title" parent="1" style="text;html=1;align=center;fontStyle=1;fontSize=10;strokeColor=none;fillColor=none;" value="Legend" vertex="1">
          <mxGeometry height="18" width="110" x="40" y="378.5" as="geometry" />
        </mxCell>
        <mxCell id="leg1" parent="1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=8;" value="LangGraph node" vertex="1">
          <mxGeometry height="22" width="90" x="50" y="401.5" as="geometry" />
        </mxCell>
        <mxCell id="leg2" parent="1" style="rhombus;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;fontSize=8;" value="Decision" vertex="1">
          <mxGeometry height="26" width="60" x="65" y="429.5" as="geometry" />
        </mxCell>
        <mxCell id="leg3" parent="1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#ffe6cc;strokeColor=#d79b00;fontSize=8;" value="Doc Analyst" vertex="1">
          <mxGeometry height="22" width="90" x="50" y="461.5" as="geometry" />
        </mxCell>
        <mxCell id="leg4" parent="1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;fontSize=8;" value="Frontend / API" vertex="1">
          <mxGeometry height="22" width="90" x="50" y="489.5" as="geometry" />
        </mxCell>
        <mxCell id="leg5" parent="1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;fontSize=8;" value="Blocked path" vertex="1">
          <mxGeometry height="22" width="90" x="50" y="517.5" as="geometry" />
        </mxCell>
        <mxCell id="leg6" parent="1" style="text;html=1;align=left;fontSize=8;strokeColor=none;fillColor=none;fontStyle=2;" value="Service (dashed)" vertex="1">
          <mxGeometry height="18" width="100" x="46" y="541.5" as="geometry" />
        </mxCell>
        <mxCell id="e1" edge="1" parent="1" source="react" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;fontSize=9;" target="fastapi" value="POST /api/v1/chat  (query · session_id · student_id · files · reasoning)">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="e2" edge="1" parent="1" source="fastapi" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;fontSize=9;" target="n1_guard" value="start workflow">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="e3" edge="1" parent="1" source="n1_guard" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;" target="d1_blocked" value="">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="e4" edge="1" parent="1" source="d1_blocked" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=0;exitY=0.5;exitDx=0;exitDy=0;entryX=1;entryY=0.5;entryDx=0;entryDy=0;fontSize=9;fontColor=#b85450;strokeColor=#b85450;" target="blocked_box" value="blocked">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="e5" edge="1" parent="1" source="d1_blocked" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;fontSize=9;fontColor=#3a6a3a;" target="n2_orch" value="pass">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="e6" edge="1" parent="1" source="blocked_box" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;fontSize=9;fontColor=#b85450;strokeColor=#b85450;dashed=1;" target="n6_responder" value="bypass">
          <mxGeometry relative="1" as="geometry">
            <Array as="points">
              <mxPoint x="115" y="650" />
              <mxPoint x="30" y="650" />
              <mxPoint x="30" y="1724" />
              <mxPoint x="385" y="1724" />
            </Array>
          </mxGeometry>
        </mxCell>
        <mxCell id="e7" edge="1" parent="1" source="n2_orch" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;" target="d2_files" value="">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="e8" edge="1" parent="1" source="d2_files" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=0;exitY=0.5;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;fontSize=9;fontColor=#d79b00;strokeColor=#d79b00;" target="n3_da" value="yes">
          <mxGeometry relative="1" as="geometry">
            <Array as="points">
              <mxPoint x="390" y="903" />
              <mxPoint x="390" y="986" />
            </Array>
          </mxGeometry>
        </mxCell>
        <mxCell id="e9" edge="1" parent="1" source="d2_files" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;fontSize=9;" target="n3_loop" value="no files">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="e10" edge="1" parent="1" source="n3_da" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.6;entryDx=0;entryDy=0;fontSize=9;dashed=1;" target="n3_loop" value="enriched context">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="e11" edge="1" parent="1" source="n3_loop" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;fontSize=9;" target="n4_validator" value="specialist_output">
          <mxGeometry relative="1" as="geometry">
            <Array as="points">
              <mxPoint x="677" y="1415" />
              <mxPoint x="540" y="1415" />
            </Array>
          </mxGeometry>
        </mxCell>
        <mxCell id="e12" edge="1" parent="1" source="n4_validator" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;" target="n5_persister" value="">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="e13" edge="1" parent="1" source="n5_persister" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;" target="n6_responder" value="">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="e14" edge="1" parent="1" source="n6_responder" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;" target="sse_response" value="">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="e15" edge="1" parent="1" source="sse_response" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=0;exitY=0.5;exitDx=0;exitDy=0;fontSize=9;strokeColor=#6c8ebf;fontColor=#1a3a6a;entryX=0;entryY=0.446;entryDx=0;entryDy=0;entryPerimeter=0;" target="react" value="SSE stream: progress events · token chunks · done event">
          <mxGeometry relative="1" as="geometry">
            <Array as="points">
              <mxPoint x="145" y="1876" />
              <mxPoint x="145" y="90" />
              <mxPoint x="370" y="90" />
            </Array>
            <mxPoint x="370" y="100" as="targetPoint" />
          </mxGeometry>
        </mxCell>
        <mxCell id="e20" edge="1" parent="1" source="n2_orch" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;fontSize=9;dashed=1;strokeColor=#9673a6;fontColor=#6a3a8a;" target="lmstudio_svc" value="LLM routing">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="e21" edge="1" parent="1" source="n3_loop" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=1;exitY=0.2;exitDx=0;exitDy=0;entryX=0;entryY=0.7;entryDx=0;entryDy=0;fontSize=9;dashed=1;strokeColor=#9673a6;fontColor=#6a3a8a;" target="lmstudio_svc" value="LLM calls (≤12 iter)">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="e22" edge="1" parent="1" source="n3_da" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=1;exitY=0.15;exitDx=0;exitDy=0;entryX=0;entryY=1;entryDx=0;entryDy=0;fontSize=9;dashed=1;strokeColor=#9673a6;fontColor=#6a3a8a;" target="lmstudio_svc" value="Vision LLM (images)">
          <mxGeometry relative="1" as="geometry">
            <Array as="points">
              <mxPoint x="960" y="1010" />
              <mxPoint x="960" y="770" />
            </Array>
          </mxGeometry>
        </mxCell>
        <mxCell id="e23" edge="1" parent="1" source="n3_da" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=1;exitY=0.6;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;fontSize=9;dashed=1;strokeColor=#82b366;fontColor=#3a6a3a;" target="ollama_svc" value="batch embed chunks">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="e24" edge="1" parent="1" source="n3_da" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=1;exitY=0.35;exitDx=0;exitDy=0;entryX=0;entryY=1;entryDx=0;entryDy=0;fontSize=9;dashed=1;strokeColor=#9673a6;fontColor=#6a3a8a;" target="neo4j_svc" value="store doc / chunks">
          <mxGeometry relative="1" as="geometry">
            <Array as="points">
              <mxPoint x="940" y="1044" />
              <mxPoint x="940" y="960" />
            </Array>
          </mxGeometry>
        </mxCell>
        <mxCell id="e25" edge="1" parent="1" source="n3_loop" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.3;entryDx=0;entryDy=0;fontSize=9;dashed=1;strokeColor=#9673a6;fontColor=#6a3a8a;" target="neo4j_svc" value="graph + vector queries">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="e26" edge="1" parent="1" source="n3_loop" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=1;exitY=0.75;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;fontSize=9;dashed=1;strokeColor=#d79b00;fontColor=#7a3e00;" target="web_search_svc" value="search_web / fetch_url">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="e27" edge="1" parent="1" source="n5_persister" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0.3;entryY=0;entryDx=0;entryDy=0;fontSize=9;dashed=1;strokeColor=#9673a6;fontColor=#6a3a8a;" target="neo4j_svc" value="long_context_summary">
          <mxGeometry relative="1" as="geometry">
            <Array as="points">
              <mxPoint x="970" y="1598" />
              <mxPoint x="970" y="880" />
            </Array>
          </mxGeometry>
        </mxCell>
        <mxCell id="e28" edge="1" parent="1" source="n6_responder" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;fontSize=9;dashed=1;strokeColor=#808080;fontColor=#505050;" target="sqlite_svc" value="conversation history">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
