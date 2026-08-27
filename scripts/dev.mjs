import { spawn } from "node:child_process";

const children = [];
let stopping = false;

function run(command, args, label) {
  const child = spawn(command, args, { stdio: "inherit", env: process.env });
  children.push(child);
  child.on("error", (error) => {
    console.error(`[${label}] ${error.message}`);
    stop(1);
  });
  child.on("exit", (code, signal) => {
    if (!stopping) {
      console.error(`[${label}] stopped (${signal ?? code ?? "unknown"})`);
      stop(code ?? 1);
    }
  });
}

function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) child.kill("SIGTERM");
  setTimeout(() => process.exit(code), 250);
}

process.on("SIGINT", () => stop(0));
process.on("SIGTERM", () => stop(0));

run("uv", ["run", "pbot", "serve", "--reload"], "harness");
run("npm", ["run", "dev:dashboard"], "dashboard");
