import { useState } from "react";
import { ProjectList } from "./components/ProjectList";
import { Editor } from "./components/Editor";

export function App() {
  const [openId, setOpenId] = useState<string | null>(null);
  return openId
    ? <Editor projectId={openId} onClose={() => setOpenId(null)} />
    : <ProjectList onOpen={setOpenId} />;
}
