// Copyright (c) 2026 Alex313031 and gz83.
// Chromium's --remote-debugging-pipe uses NUL-delimited JSON on fd 3/4.
export class CDP {
  constructor(input, output, onEvent = () => {}) {
    this.input = input;
    this.pending = new Map();
    this.sequence = 0;
    this.buffer = '';
    this.failure = null;
    this.onEvent = onEvent;
    output.setEncoding('utf8');
    output.on('data', chunk => {
      this.buffer += chunk;
      let end;
      while ((end = this.buffer.indexOf('\0')) >= 0) {
        const message = this.buffer.slice(0, end);
        this.buffer = this.buffer.slice(end + 1);
        try { this.receive(JSON.parse(message)); }
        catch (error) { this.fail(error); }
      }
    });
    output.on('end', () => this.fail(new Error('DevTools pipe closed')));
    output.on('error', error => this.fail(error));
    input.on('error', error => this.fail(error));
  }

  receive(message) {
    if (message.method) {
      this.onEvent(message);
      if (['Target.targetCrashed', 'Inspector.targetCrashed'].includes(message.method)) {
        this.fail(new Error(`Renderer crashed: ${JSON.stringify(message)}`));
      }
      return;
    }
    const pending = this.pending.get(message.id);
    if (!pending) return;
    this.pending.delete(message.id);
    clearTimeout(pending.timer);
    if (message.error) pending.reject(new Error(JSON.stringify(message.error)));
    else pending.resolve(message.result);
  }

  fail(error) {
    this.failure ??= error;
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(this.failure);
    }
    this.pending.clear();
  }

  call(method, params = {}, sessionId, timeout = 15000) {
    if (this.failure) return Promise.reject(this.failure);
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`DevTools timeout: ${method}`));
      }, timeout);
      this.pending.set(id, {resolve, reject, timer});
      this.input.write(JSON.stringify({id, method, params, sessionId}) + '\0');
    });
  }
}
