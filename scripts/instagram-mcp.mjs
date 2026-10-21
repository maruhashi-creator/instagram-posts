// Instagram MCP サーバーの起動スクリプト。
//
// @luminarylane/instagram-mcp-server v1.6.10 の dist/index.js は
// `import.meta.url === file://${process.argv[1]}` で直接実行かどうかを判定しているが、
// Windows では import.meta.url が file:///C:/... 、argv[1] が C:\... になり一致しない。
// そのため直接起動しても main() が呼ばれず、何も出力せずに終了してしまう。
// ここではエクスポートされている server を読み込み、stdio に接続して起動する。
import { server } from "@luminarylane/instagram-mcp-server";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

try {
  await server.connect(new StdioServerTransport());
  console.error("Instagram MCP Server running on stdio");
} catch (e) {
  console.error("Fatal:", e);
  process.exit(1);
}
