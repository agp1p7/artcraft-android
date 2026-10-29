
thread_local! {
    static GPU_DIAG_V5_PARAMS: std::cell::RefCell<Vec<(String, Vec<u32>, Buf)>> = const { std::cell::RefCell::new(Vec::new()) };
}
pub(crate) fn gpu_diag_v5_records() -> Vec<(String, Vec<u32>, Buf)> {
    GPU_DIAG_V5_PARAMS.with(|r| std::mem::take(&mut *r.borrow_mut()))
}
pub(crate) struct V5CopyKernel {
    pipeline: wgpu::ComputePipeline,
    layout: wgpu::BindGroupLayout,
}
impl Gpu {
    fn gpu_diag_v5_params(&self, enc: &mut wgpu::CommandEncoder, name: &str, p: &[u32], params: &wgpu::Buffer) {
        if !["wb_k", "chroma_k"].contains(&name) || p.first().copied().unwrap_or(0) < (16 << 20) { return; }
        let offset = p.last().copied().unwrap_or(0);
        let n = p[0];
        if offset != 0 && offset.saturating_add(1 << 20) < n && !(offset <= n / 2 && n / 2 < offset.saturating_add(1 << 20)) { return; }
        let shader = self.device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("v5 actual parameter echo"),
            source: wgpu::ShaderSource::Wgsl(r#"
@group(0) @binding(0) var<storage, read> P: array<u32>;
@group(0) @binding(1) var<storage, read_write> O: array<u32>;
@compute @workgroup_size(1) fn main() {
    let n = arrayLength(&P);
    O[0] = n;
    O[1] = P[n - 1u];
    for (var i = 0u; i < n; i++) { O[i + 2u] = P[i]; }
}"#.into()),
        });
        let pipeline = self.device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("v5 parameter echo"), layout: None, module: &shader,
            entry_point: Some("main"), compilation_options: Default::default(), cache: None,
        });
        let output = self.buffer(p.len() + 2);
        let bg = self.device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("v5 same production params"), layout: &pipeline.get_bind_group_layout(0),
            entries: &[
                wgpu::BindGroupEntry { binding: 0, resource: params.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 1, resource: output.raw().as_entire_binding() },
            ],
        });
        {
            let mut pass = enc.begin_compute_pass(&wgpu::ComputePassDescriptor { label: Some("v5 parameter echo"), timestamp_writes: None });
            pass.set_pipeline(&pipeline); pass.set_bind_group(0, &bg, &[]); pass.dispatch_workgroups(1, 1, 1);
        }
        GPU_DIAG_V5_PARAMS.with(|r| r.borrow_mut().push((name.to_owned(), p.to_vec(), output)));
    }
    pub(crate) fn gpu_diag_v5_fresh(&self, len: usize) -> Buf {
        let size = (len.max(1) * 4) as u64;
        if size > self.limit() { self.over_limit(size); return self.buffer(len); }
        Buf { buf: Some(Tracked::new(self.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("v5 independent fresh scratch"), size,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        }))), len }
    }
    pub(crate) fn gpu_diag_v5_copy_kernel(&self) -> V5CopyKernel {
        let shader = self.device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("v5 independent fill and copy"),
            source: wgpu::ShaderSource::Wgsl(r#"
@group(0) @binding(0) var<storage, read> P: array<u32>;
@group(0) @binding(1) var<storage, read> A: array<f32>;
@group(0) @binding(2) var<storage, read_write> O: array<f32>;
@compute @workgroup_size(256) fn main(@builtin(global_invocation_id) g: vec3<u32>) {
    if (g.x >= P[2]) { return; }
    let i = g.x + P[1];
    if (i >= P[0]) { return; }
    for (var c = 0u; c < 3u; c++) {
        if (P[3] == 0u) { O[3u * i + c] = -12345.0; }
        else { O[3u * i + c] = A[3u * i + c]; }
    }
}"#.into()),
        });
        let pipeline = self.device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("v5 independent copy"), layout: None, module: &shader,
            entry_point: Some("main"), compilation_options: Default::default(), cache: None,
        });
        let layout = pipeline.get_bind_group_layout(0);
        V5CopyKernel { pipeline, layout }
    }
    pub(crate) fn gpu_diag_v5_copy_run(&self, enc: &mut wgpu::CommandEncoder, kernel: &V5CopyKernel, src: &Buf, dst: &Buf, p: [u32; 4]) {
        let params = self.device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("v5 copy params"), contents: bytemuck::cast_slice(&p), usage: wgpu::BufferUsages::STORAGE,
        });
        let bg = self.device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("v5 copy bindings"), layout: &kernel.layout,
            entries: &[
                wgpu::BindGroupEntry { binding: 0, resource: params.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 1, resource: src.raw().as_entire_binding() },
                wgpu::BindGroupEntry { binding: 2, resource: dst.raw().as_entire_binding() },
            ],
        });
        let mut pass = enc.begin_compute_pass(&wgpu::ComputePassDescriptor { label: Some("v5 independent copy"), timestamp_writes: None });
        pass.set_pipeline(&kernel.pipeline); pass.set_bind_group(0, &bg, &[]);
        pass.dispatch_workgroups(p[2].div_ceil(256), 1, 1);
    }
}
