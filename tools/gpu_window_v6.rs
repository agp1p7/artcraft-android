
impl Gpu {
    fn gpu_window_v6(&self, enc: &mut wgpu::CommandEncoder, name: &str, p: &[u32], bufs: &[Option<&Buf>]) -> bool {
        let strides: [u64; 4] = match name {
            "log_lum_k" | "dark_k" => [3, 0, 0, 1],
            "guided_pre" => [1, 0, 0, 2], "guided_ab" => [2, 0, 0, 2],
            "guided_apply" => [1, 2, 0, 1],
            "wb_k" | "chroma_k" | "redeye_k" => [3, 0, 0, 3],
            "nr_lum" => [3, 1, 1, 3], "nr_col" => [3, 3, 3, 3],
            "xguided_pre" => [1, 1, 0, 2], "xguided_ab" => [2, 2, 0, 2],
            "xguided_apply" => [1, 2, 1, 1],
            "subsample" => [p.get(1).copied().unwrap_or(0) as u64, 0, 0, 1],
            _ => return false,
        };
        if failed() { return true; }
        let Some(&count) = p.first() else { fail(FailKind::Fatal, format!("v6 {name}: missing count")); return true; };
        if count == 0 { return true; }
        if bufs.len() != 4 || (name == "subsample" && strides[0] == 0) { fail(FailKind::Fatal, format!("v6 {name}: invalid bindings")); return true; }
        let Some(k) = self.kernels.get(name) else { fail(FailKind::Fatal, format!("v6 {name}: missing kernel")); return true; };
        let alignment = self.device.limits().min_storage_buffer_offset_alignment as u64;
        let mut offset = 0u32;
        while offset < count {
            let take = (count - offset).min(1 << 20);
            let mut local = p.to_vec(); local[0] = take; local.push(offset);
            let params = self.device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                label: Some("v6 window params"), contents: bytemuck::cast_slice(&local), usage: wgpu::BufferUsages::STORAGE,
            });
            let mut entries = vec![wgpu::BindGroupEntry { binding: 0, resource: params.as_entire_binding() }];
            for (i, stride) in strides.iter().copied().enumerate() {
                if stride == 0 { entries.push(wgpu::BindGroupEntry { binding: i as u32 + 1, resource: self.dummy.as_entire_binding() }); continue; }
                let Some(buf) = bufs[i] else { fail(FailKind::Fatal, format!("v6 {name}: missing binding {i}")); return true; };
                let start = offset as u64 * stride;
                let words = if name == "subsample" && i == 0 { (take as u64 - 1) * stride + 1 } else { take as u64 * stride };
                let bytes = words * 4; let byte_offset = start * 4;
                if start + words > buf.len as u64 || byte_offset + bytes > buf.raw().size() || bytes > self.limit() || (alignment > 0 && byte_offset % alignment != 0) {
                    fail(FailKind::Fatal, format!("v6 {name}: invalid window binding={i} offset={byte_offset} bytes={bytes}")); return true;
                }
                entries.push(wgpu::BindGroupEntry { binding: i as u32 + 1, resource: wgpu::BindingResource::Buffer(wgpu::BufferBinding { buffer: buf.raw(), offset: byte_offset, size: wgpu::BufferSize::new(bytes) }) });
            }
            let bg = self.device.create_bind_group(&wgpu::BindGroupDescriptor { label: Some("v6 bounded bindings"), layout: &k.layout, entries: &entries });
            {
                let mut pass = enc.begin_compute_pass(&wgpu::ComputePassDescriptor { label: Some(name), timestamp_writes: None });
                pass.set_pipeline(&k.pipeline); pass.set_bind_group(0, &bg, &[]); pass.dispatch_workgroups(take.div_ceil(256), 1, 1);
            }
            if offset == 0 || offset + take == count { log::warn!("gpu-diag: candidate-v6 kernel={} total={} window_start={} window_count={} strides={:?} bounded=true", name, count, offset, take, strides); }
            offset += take;
        }
        true
    }
}
