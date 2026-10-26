import { runStdioBridge } from "./server";

runStdioBridge().catch((error) => {
  process.stderr.write(`[hellboy] fatal: ${(error as Error).message}\n`);
  process.exit(1);
});
